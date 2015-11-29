#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
from sklearn.datasets import load_files


here = os.path.dirname(os.path.abspath(__file__))


def get_raw(which_set):
    if which_set not in ('train', 'test'):
        raise ValueError

    data_dir = os.path.join(here, '../data/raw_{0}'.format(which_set))
    data = load_files(data_dir, load_content=False, shuffle=False)
    return data


def get_mask():
    data_dir = os.path.join(here, '../data/mask')
    data = load_files(data_dir, load_content=False, shuffle=False)
    return data
