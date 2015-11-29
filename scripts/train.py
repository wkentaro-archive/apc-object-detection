#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import datetime
import logging
import os
import os.path as osp
import pickle
import sys

from chainer import cuda
from chainer import optimizers as O
from chainer import serializers
from chainer import Variable
import cv2
import numpy as np

from apc_od import get_raw
from apc_od import im_preprocess
from apc_od import im_to_blob
from draw_loss import draw_loss_curve
from tile_ae_encoded import tile_ae_encoded
from tile_ae_inout import tile_ae_inout


here = osp.dirname(osp.abspath(__file__))


class Trainer(object):

    def __init__(self, model, is_supervised, log_dir, log_file, on_gpu):
        self.model = model
        self.is_supervised = is_supervised
        self.log_dir = log_dir
        self.log_file = log_file
        self.on_gpu = on_gpu
        # setup model on gpu
        if self.on_gpu:
            self.model.to_gpu()
        # optimizer
        self.optimizer = O.Adam(alpha=0.001)
        self.optimizer.setup(self.model)

    def batch_loop(self, dataset, train, batch_size=10):
        files = dataset.filenames
        target = dataset.target
        N = len(files)
        # train loop
        sum_loss = 0
        sum_accuracy = 0 if self.is_supervised else None
        perm = np.random.permutation(N)
        for i in range(0, N, batch_size):
            files_batch = files[perm[i:i + batch_size]]
            x_batch = np.array([im_to_blob(im_preprocess(cv2.imread(f)))
                                for f in files_batch])
            y_batch = target[perm[i:i + batch_size]].astype(np.int32)
            if self.on_gpu:
                x_batch = cuda.to_gpu(x_batch)
                y_batch = cuda.to_gpu(y_batch)
            x = Variable(x_batch, volatile=not train)
            y = Variable(y_batch, volatile=not train)
            if self.is_supervised:
                inputs = [x, y]
            else:
                inputs = [x]
            self.optimizer.zero_grads()
            loss, y = self.model(*inputs, train=train)
            loss.backward()
            self.optimizer.update()
            sum_loss += float(loss.data)
            if self.is_supervised:
                sum_accuracy += float(loss.data)
        y_data = y.data
        if self.on_gpu:
            x_batch = cuda.to_cpu(x_batch)
            y_data = cuda.to_cpu(y_data)
        return sum_loss, sum_accuracy, x_batch, y_data

    def main_loop(self, n_epoch=10, save_interval=None, save_encoded=True):
        save_interval = save_interval or (n_epoch // 10)
        train_data = get_raw(which_set='train')
        test_data = get_raw(which_set='test')
        N_train = len(train_data.filenames)
        N_test = len(test_data.filenames)
        for epoch in xrange(0, n_epoch):
            # train
            sum_loss, sum_accuracy, _, _ = self.batch_loop(train_data,
                                                           train=True)
            # logging
            mean_loss = sum_loss / N_train
            msg = 'epoch:{:02d}; train mean loss={};'.format(epoch, mean_loss)
            if self.is_supervised:
                mean_accuracy = sum_accuracy / N_train
                msg += ' accuracy={};'.format(mean_accuracy)
            logging.info(msg)
            print(msg)
            # test
            sum_loss, sum_accuracy, x_data, y_data = \
                self.batch_loop(test_data, train=False)
            # logging
            mean_loss = sum_loss / N_test
            msg = 'epoch:{:02d}; test mean loss={};'.format(epoch, mean_loss)
            if self.is_supervised:
                mean_accuracy = sum_accuracy / N_test
                msg += ' accuracy={};'.format(mean_accuracy)
            logging.info(msg)
            print(msg)
            # save model and input/encoded/decoded
            if epoch % save_interval == (save_interval - 1):
                print('epoch:{:02d}; saving'.format(epoch))
                # save model
                model_path = osp.join(
                    self.log_dir,
                    '{name}_model_{epoch}.h5'.format(name=self.model.name,
                                                     epoch=epoch))
                serializers.save_hdf5(model_path, self.model)
                # save x_data
                x_path = osp.join(self.log_dir, 'x_{}.pkl'.format(epoch))
                with open(x_path, 'wb') as f:
                    pickle.dump(x_data, f)  # save x
                if not self.is_supervised:
                    x_hat_path = osp.join(self.log_dir,
                                          'x_hat_{}.pkl'.format(epoch))
                    with open(x_hat_path, 'wb') as f:
                        pickle.dump(y_data, f)  # save x_hat
                    tile_ae_inout(
                        x_data, y_data,
                        osp.join(self.log_dir, 'X_{}.jpg'.format(epoch)))
                if save_encoded:
                    x = Variable(cuda.to_gpu(x_data), volatile=True)
                    z = self.model.encode(x)
                    tile_ae_encoded(
                        cuda.to_cpu(z.data),
                        osp.join(self.log_dir,
                                 'x_encoded_{}.jpg'.format(epoch)))

        draw_loss_curve(self.log_file,
                        osp.join(self.log_dir, 'loss_curve.jpg'),
                        no_acc=not self.is_supervised)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'supervised_or_not', type=str, choices=['supervised', 'unsupervised'],
        help='do supervised or unsupervised training')
    parser.add_argument('--epoch', type=int, default=50,
                        help='number of recursion (default: 50)')
    parser.add_argument('--no-logging', action='store_true',
                        help='logging to tmp dir')
    parser.add_argument('--save-interval', type=int, default=None,
                        help='save interval of x and x_hat')
    parser.add_argument('-m', '--model', required=True, help='name of model')
    args = parser.parse_args()

    n_epoch = args.epoch
    save_interval = args.save_interval
    is_supervised = True if args.supervised_or_not == 'supervised' else False

    if is_supervised:
        if args.model == 'VGG_mini_ABN':
            from apc_od.models import VGG_mini_ABN
            model = VGG_mini_ABN()
            save_encoded = False
        else:
            sys.stderr.write('Unsupported model: {}\n'.format(args.model))
            sys.exit(1)
    else:
        # unsupervised
        if args.model == 'CAE':
            from apc_od.models import CAE
            model = CAE()
            save_encoded = True
        elif args.model == 'CAEOnes':
            from apc_od.models import CAEOnes
            model = CAEOnes()
            save_encoded = False
        elif args.model == 'CAEPool':
            from apc_od.models import CAEPool
            model = CAEPool()
            save_encoded = True
        else:
            sys.stderr.write('Unsupported model: {}\n'.format(args.model))
            sys.exit(1)

    timestamp = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
    # setup for logging
    if args.no_logging:
        import tempfile
        log_dir = tempfile.mkdtemp()
    else:
        log_dir = osp.join(here, '../logs/{}_{}'.format(timestamp, args.model))
        log_dir = osp.realpath(osp.abspath(log_dir))
        os.mkdir(log_dir)
    log_file = osp.join(log_dir, 'log.txt')
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename=log_file,
        level=logging.DEBUG,
    )
    logging.info('args: {};'.format(args))
    msg = 'logging in {};'.format(log_dir)
    logging.info(msg)
    print(msg)

    trainer = Trainer(
        model=model,
        is_supervised=is_supervised,
        log_dir=log_dir,
        log_file=log_file,
        on_gpu=True,
    )
    trainer.main_loop(
        n_epoch=n_epoch,
        save_interval=save_interval,
        save_encoded=save_encoded,
    )


if __name__ == '__main__':
    main()
