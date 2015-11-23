#!/usr/bin/env python
# -*- coding: utf-8 -*-

from chainer import optimizers
from chainer import Variable
import numpy as np
from skimage.data import astronaut

from apc_od import im_to_blob
from apc_od.models import CAEPool


def test_cae_pool_train():
    img = astronaut()
    x_data = np.array([im_to_blob(img)])
    x = Variable(x_data, volatile=False)

    model = CAEPool()
    optimizer = optimizers.Adam()
    optimizer.setup(model)

    optimizer.zero_grads()
    loss, x_hat = model(x)
    loss.backward()


def test_cae_pool_encode():
    img = astronaut()
    x_data = np.array([im_to_blob(img)])
    x = Variable(x_data, volatile=True)

    model = CAEPool()
    model.encode(x)


def test_cae_pool_decode():
    img = astronaut()
    x_data = np.array([im_to_blob(img)])
    x = Variable(x_data, volatile=True)

    model = CAEPool()
    h = model.encode(x)
    model.decode(h)
