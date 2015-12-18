#!/usr/bin/env python
# -*- coding: utf-8 -*-

import chainer
from chainer import cuda
import chainer.functions as F
from chainer import serializers
from chainer import Variable
import cupy
import numpy as np
from skimage.transform import resize

from apc_od import blob_to_im
from apc_od import im_to_blob
from apc_od.models.cae_ones import CAEOnes
from apc_od.models.vgg_mini_abn import VGG_mini_ABN


class Pipeline(chainer.Chain):
    pass


class CAEOnesRoiVGG(Pipeline):

    def __init__(
            self,
            initial_roi,
            learning_rate=0.1,
            learning_n_sample=1000
            ):
        super(CAEOnesRoiVGG, self).__init__(
            cae_ones1=CAEOnes(),
            vgg2=VGG_mini_ABN(),
        )
        self.initial_roi = initial_roi
        self.learning_rate = learning_rate
        self.learning_n_sample = learning_n_sample

        self.train = True
        self.y = None
        self.accuracy = None
        self.pred = None

    def x0_to_x1(self, x0, roi_scale):
        on_gpu = isinstance(x0.data, cupy.ndarray)
        roi_scale_data = cuda.to_cpu(roi_scale.data) \
            if on_gpu else roi_scale.data
        rois_data = (self.initial_roi * roi_scale_data).astype(int)
        x0_data = cuda.to_cpu(x0.data) if on_gpu else x0.data
        cropped = []
        for i in xrange(len(x0_data)):
            roi = rois_data[i]
            im = blob_to_im(x0_data[i])
            im = im[roi[0]:roi[2], roi[1]:roi[3]]
            if im.size == 0:
                break
            im = resize(im, (128, 128), preserve_range=True)
            cropped.append(im_to_blob(im))
        else:
            cropped_data = np.array(cropped, dtype=np.float32)
            if on_gpu:
                cropped_data = cuda.to_gpu(cropped_data)
            x1 = Variable(cropped_data, volatile=not self.train)
            return x1

    def random_sample(self, x, t):
        """Randomly changes the parameters of each link.

        returns better parameters to regress for the task to get ``t``
        """
        on_gpu = isinstance(x.data, cupy.ndarray)

        self.cae_ones1.to_gpu()
        roi_scale = self.cae_ones1.encode(x)
        self.cae_ones1.to_cpu()

        self.vgg2.to_gpu()
        rands_shape = [self.learning_n_sample] + list(roi_scale.data.shape)
        rands = self.learning_rate * \
            (2 * np.random.random(rands_shape) - 1) + 1
        rands[0] = np.ones(roi_scale.data.shape)
        roi_scale_data = cuda.to_cpu(roi_scale.data) \
            if on_gpu else roi_scale.data
        min_rand = None
        for i, rand in enumerate(rands):
            roi_scale_data_with_rand = rand * roi_scale_data
            roi_scale = Variable(roi_scale_data_with_rand,
                                 volatile=not self.train)
            x1 = self.x0_to_x1(x0=x, roi_scale=roi_scale)
            if x1 is None:
                continue
            self.vgg2(x1, t)
            h = self.vgg2.y
            loss = F.softmax_cross_entropy(h, t)
            if min_rand is None:
                min_rand = rand
                min_loss_data = float(loss.data)
            elif min_loss_data > float(loss.data):
                min_rand = rand
                min_loss_data = float(loss.data)
        self.vgg2.to_cpu()

        # DEBUG
        # from skimage.io import imsave
        # timestamp = str(time.time())
        # os.mkdir(timestamp)
        # for i, (xi, roi) in enumerate(zip(x_data, min_rois)):
        #     im = blob_to_im(xi)
        #     im = im[roi[0]:roi[2], roi[1]:roi[3]]
        #     imsave('{}/{}.jpg'.format(timestamp, i), im)

        if min_rand is None:
            # no minimum randomness is found, so regress to ones
            min_rand = np.ones(roi_scale.data.shape)

        # convert from xp.ndarray to chainer.Variable
        roi_scale_data_with_rand = min_rand * roi_scale.data
        roi_scale_data_with_rand = roi_scale_data_with_rand.astype(np.float32)
        if on_gpu:
            roi_scale_data_with_rand = cuda.to_gpu(roi_scale_data_with_rand)
        roi_scale = Variable(roi_scale_data_with_rand, volatile=not self.train)
        t0 = roi_scale

        x1 = self.x0_to_x1(x0=x, roi_scale=roi_scale)

        return t0, x1

    def __call__(self, x, t=None):
        self.cae_ones1.train = self.train
        self.vgg2.train = self.train

        self.cae_ones1.to_cpu()
        self.vgg2.to_cpu()

        # just use as regression
        if t is None:
            # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
            # testing fase
            # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
            self.cae_ones1.to_gpu()
            roi_scale = self.cae_ones1.encode(x)
            self.cae_ones1.to_cpu()
            x1 = self.x0_to_x1(x0=x, roi_scale=roi_scale)
            self.vgg2.to_gpu()
            self.vgg2(x1)
            self.vgg2.to_cpu()
            self.y = self.vgg2.y
            return self.y

        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        # training fase
        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        # estimate better parameters
        t0, x1 = self.random_sample(x, t)
        if x1 is None:
            return
        # optimize roi parameter to be better
        z = self.cae_ones1.z
        loss1 = F.mean_squared_error(z, t0)
        # optimize regression parameter to be better
        self.vgg2.to_gpu()
        loss2 = self.vgg2(x1, t)

        self.accuracy = self.vgg2.accuracy
        return loss1, loss2
