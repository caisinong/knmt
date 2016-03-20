#!/usr/bin/env python
"""utils.py: Various utilitity functions for RNNSearch"""
__author__ = "Fabien Cromieres"
__license__ = "undecided"
__version__ = "1.0"
__email__ = "fabien.cromieres@gmail.com"
__status__ = "Development"

import os
import logging
import numpy as np
import chainer
from chainer import Variable, cuda

logging.basicConfig()
log = logging.getLogger("rnns:utils")
log.setLevel(logging.INFO)

def ensure_path(path):
    try: 
        os.makedirs(path)
        log.info("Created directory %s" % path)
    except OSError:
        if not os.path.isdir(path):
            raise
        
def make_batch_src(src_data, padding_idx = 0, gpu = None, volatile = "off"):
    max_src_size = max(len(x) for x  in src_data)
    min_src_size = min(len(x) for x  in src_data)
    mb_size = len(src_data)
    
    src_batch = [np.empty((mb_size,), dtype = np.int32) for _ in xrange(max_src_size)]
    src_mask = [np.empty((mb_size,), dtype = np.bool) for _ in xrange(max_src_size - min_src_size)]
    
    for num_ex in xrange(mb_size):
        this_src_len = len(src_data[num_ex])
        for i in xrange(max_src_size):
            if i < this_src_len:
                src_batch[i][num_ex] = src_data[num_ex][i]
                if i >= min_src_size:
                    src_mask[i - min_src_size][num_ex] = True
            else:
                src_batch[i][num_ex] = padding_idx
                assert i >= min_src_size
                src_mask[i - min_src_size][num_ex] = False

    if gpu is not None:
        return ([Variable(cuda.to_gpu(x, gpu), volatile = volatile) for x in src_batch],
                [cuda.to_gpu(x, gpu) for x in src_mask])
    else:
        return [Variable(x, volatile = volatile) for x in src_batch], src_mask              
                
def make_batch_src_tgt(training_data, eos_idx = 1, padding_idx = 0, gpu = None, volatile = "off", need_arg_sort = False):
    if need_arg_sort:
        training_data_with_argsort = zip(training_data, range(len(training_data)))
        training_data_with_argsort.sort(key = lambda x:len(x[0][1]), reverse = True)
        training_data, argsort = zip(*training_data_with_argsort)
    else:
        training_data = sorted(training_data, key = lambda x:len(x[1]), reverse = True)
#     max_src_size = max(len(x) for x, y  in training_data)
    max_tgt_size = max(len(y) for _, y  in training_data)
    mb_size = len(training_data)
    
    src_batch, src_mask = make_batch_src(
                [x for x,y in training_data], padding_idx = padding_idx, gpu = gpu, volatile = volatile)
    
    lengths_list = []
    lowest_non_finished = mb_size -1
    for pos in xrange(max_tgt_size + 1):
        while pos > len(training_data[lowest_non_finished][1]):
            lowest_non_finished -= 1
            assert lowest_non_finished >= 0
        mb_length_at_this_pos = lowest_non_finished + 1
        assert len(lengths_list) == 0 or mb_length_at_this_pos <= lengths_list[-1]
        lengths_list.append(mb_length_at_this_pos)
        
    tgt_batch = []
    for i in xrange(max_tgt_size + 1):
        current_mb_size = lengths_list[i]
        assert current_mb_size > 0
        tgt_batch.append(np.empty((current_mb_size,), dtype = np.int32))
        for num_ex in xrange(current_mb_size):
            assert len(training_data[num_ex][1]) >= i
            if len(training_data[num_ex][1]) == i:
                tgt_batch[-1][num_ex] = eos_idx
            else:
                tgt_batch[-1][num_ex] = training_data[num_ex][1][i]
        
    if gpu is not None:
        tgt_batch_v = [Variable(cuda.to_gpu(x, gpu), volatile = volatile) for x in tgt_batch]
    else:
        tgt_batch_v = [Variable(x, volatile = volatile) for x in tgt_batch]
    
    if need_arg_sort:
        return src_batch, tgt_batch_v, src_mask, argsort
    else:
        return src_batch, tgt_batch_v, src_mask

def minibatch_looper_random(data, mb_size):
    while 1:
        training_data_sampled = [None] * mb_size
        r = np.random.randint(0,len(data), size = (mb_size,))
        for i in range(mb_size):
            training_data_sampled[i] = data[r[i]]
        yield training_data_sampled

def minibatch_looper(data, mb_size, loop = True, avoid_copy = False):
    current_start = 0
    data_exhausted = False
    while not data_exhausted:
        if avoid_copy and len(data) >= current_start + mb_size:
            training_data_sampled = data[current_start: current_start + mb_size]
            current_start += mb_size
            if current_start >= len(data):
                if loop:
                    current_start = 0
                else:
                    data_exhausted = True
                    break
        else:
            training_data_sampled = []
            while len(training_data_sampled) < mb_size:
                remaining = mb_size - len(training_data_sampled)
                training_data_sampled += data[current_start:current_start + remaining]
                current_start += remaining
                if current_start >= len(data):
                    if loop:
                        current_start = 0
                    else:
                        data_exhausted = True
                        break
        
        yield training_data_sampled
        
def batch_sort_and_split(batch, size_parts, sort_key = lambda x:len(x[1]), inplace = False):
    if not inplace:
        batch = list(batch)
    batch.sort(key = sort_key)
    nb_mb_for_sorting = len(batch) / size_parts + (1 if len(batch) % size_parts != 0 else 0)
    for num_batch in xrange(nb_mb_for_sorting):
        mb_raw = batch[num_batch * size_parts : (num_batch + 1) * size_parts]
        yield mb_raw
     
def mb_reverser(mb_raw, reverse_src = False, reverse_tgt = False):
    if reverse_src or reverse_tgt:
        mb_raw_new = []
        for src_side, tgt_side in mb_raw:
            if reverse_src:
                src_side = src_side[::-1]
            if reverse_tgt:
                tgt_side = tgt_side[::-1]
            mb_raw_new.append((src_side, tgt_side))
        return mb_raw_new
    else:
        return mb_raw
    
def minibatch_provider(data, eos_idx, mb_size, nb_mb_for_sorting = 1, loop = True, inplace_sorting = False, gpu = None,
                       randomized = False, volatile = "off", sort_key = lambda x:len(x[1]),
                       reverse_src = False, reverse_tgt = False
                       ):
    if nb_mb_for_sorting == -1:
        assert not randomized
        assert loop == False
        for mb_raw in batch_sort_and_split(data, mb_size, inplace = inplace_sorting, sort_key = sort_key):
            mb_raw = mb_reverser(mb_raw, reverse_src = reverse_src, reverse_tgt = reverse_tgt)
            src_batch, tgt_batch, src_mask = make_batch_src_tgt(mb_raw, eos_idx = eos_idx, gpu = gpu, volatile = volatile)
            yield src_batch, tgt_batch, src_mask
    else:
        assert nb_mb_for_sorting > 0
        required_data = nb_mb_for_sorting * mb_size
        if randomized:
#             assert not loop
            looper = minibatch_looper_random(data, required_data)
        else:
            looper = minibatch_looper(data, required_data, loop = loop, avoid_copy = False)
        for large_batch in looper:
            # ok to sort in place since minibatch_looper will return copies
            for mb_raw in batch_sort_and_split(large_batch, mb_size, inplace = True, sort_key = sort_key):
                mb_raw = mb_reverser(mb_raw, reverse_src = reverse_src, reverse_tgt = reverse_tgt)
                src_batch, tgt_batch, src_mask = make_batch_src_tgt(mb_raw, eos_idx = eos_idx, gpu = gpu, volatile = volatile)
                yield src_batch, tgt_batch, src_mask
             
def compute_bleu_with_unk_as_wrong(references, candidates, is_unk_id, new_unk_id_ref, new_unk_id_cand):
    import bleu_computer
    assert new_unk_id_ref != new_unk_id_cand
    bc = bleu_computer.BleuComputer()
    for ref, cand in zip(references, candidates):
        ref_mod = tuple((x if not is_unk_id(x) else new_unk_id_ref) for x in ref)
        cand_mod = tuple((int(x) if not is_unk_id(int(x)) else new_unk_id_cand) for x in cand)
        bc.update(ref_mod, cand_mod)
    return bc

def de_batch(batch, mask = None, eos_idx = None, is_variable = False, raw = False):
    """ Utility function for "de-batching".
        batch is a list of Variable/numpy/cupy of shape[0] <= mb_size
        
        returns a list of the sequences in the batch
    
    """
    res = []  
    mb_size = len(batch[0].data) if is_variable else len(batch[0])
    if mask is not None:
        mask_offset = len(batch) - len(mask)
        assert mask_offset >= 0
    for sent_num in xrange(mb_size):
        assert sent_num == len(res)
        res.append([])
        for src_pos in range(len(batch)):
            current_batch_size = batch[src_pos].data.shape[0] if is_variable else batch[src_pos].shape[0]
            if (mask is None or 
                    (src_pos < mask_offset or mask[src_pos - mask_offset][sent_num])) and current_batch_size > sent_num:
#                 print sent_num, src_pos, batch[src_pos].data
                idx = batch[src_pos].data[sent_num] if is_variable else batch[src_pos][sent_num]
                if not raw:
                    idx = int(idx)
                res[sent_num].append(None)
                res[sent_num][src_pos]  = idx
                if eos_idx is not None and idx == eos_idx:
                    break
    return res

def gen_ortho(shape):
    # adapted from code in the lasagne nn library
    a = np.random.randn(*shape)
    u, _, v = np.linalg.svd(a, full_matrices=False)
    # pick the one with the correct shape
    q = u if u.shape == a.shape else v
    return q.astype(np.float32)

def ortho_init(link):
    if isinstance(link, chainer.links.Linear):
        print "init ortho", link
        link.W.data[...] = gen_ortho(link.W.data.shape)
    elif isinstance(link, chainer.links.GRU):
        print "init ortho", link
        for name_lin in "W_r U_r W_z U_z W U".split(" "):
            print "case", name_lin, getattr(link, name_lin)
            ortho_init(getattr(link, name_lin))
    elif isinstance(link, chainer.links.Maxout):
        print "init ortho", link
        ortho_init(link.linear)
    else:
        raise NotImplemented