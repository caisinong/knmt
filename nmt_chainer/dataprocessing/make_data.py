#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""make_data.py: prepare data for training"""
__author__ = "Fabien Cromieres"
__license__ = "undecided"
__version__ = "1.0"
__email__ = "fabien.cromieres@gmail.com"
__status__ = "Development"

import collections
import logging
import codecs
import json
import operator
import os.path
import gzip

from nmt_chainer.utilities.utils import ensure_path
from indexer import Indexer

# import h5py

logging.basicConfig()
log = logging.getLogger("rnns:make_data")
log.setLevel(logging.INFO)


MakeDataInfosOneSide = collections.namedtuple(
    "MakeDataInfosOneSide", ["total_count_unk", "total_token", "nb_ex"])

MakeDataInfos = collections.namedtuple("MakeDataInfos", ["total_count_unk_src", "total_count_unk_tgt", "total_token_src",
                                                         "total_token_tgt", "nb_ex"])


def segment(line, type="word"):
    if type == "word":
        return line.split(" ")
    elif type == "word2char":
        return tuple("".join(line.split(" ")))
    elif type == "char":
        return tuple(line)
    else:
        raise NotImplemented


def build_index_from_string(str, voc_limit=None, max_nb_ex=None, segmentation_type="word"):
    counts = collections.defaultdict(int)
    line = segment(str.strip(), type=segmentation_type)  # .split(" ")

    for w in line:
        counts[w] += 1

    sorted_counts = sorted(
        counts.items(), key=operator.itemgetter(1), reverse=True)

    res = Indexer()

    for w, _ in sorted_counts[:voc_limit]:
        res.add_word(w, should_be_new=True)
    res.finalize()

    return res

def build_index(fn, voc_limit=None, max_nb_ex=None, segmentation_type="word"):
    f = codecs.open(fn, encoding="utf8")
    counts = collections.defaultdict(int)
    for num_ex, line in enumerate(f):
        if max_nb_ex is not None and num_ex >= max_nb_ex:
            break
        line = segment(line.strip(), type=segmentation_type)  # .split(" ")
        for w in line:
            counts[w] += 1

    sorted_counts = sorted(
        counts.items(), key=operator.itemgetter(1), reverse=True)

    res = Indexer()

    for w, _ in sorted_counts[:voc_limit]:
        res.add_word(w, should_be_new=True)
    res.finalize()

    return res


def build_dataset_one_side_from_string(src_str, src_voc_limit=None, max_nb_ex=None, dic_src=None,
                           segmentation_type = "word"):
    if dic_src is None:
        log.info("building src_dic")
        dic_src = build_index_from_string(src_str, src_voc_limit, max_nb_ex,
                              segmentation_type = segmentation_type)

    log.info("start indexing")

    res = []

    num_ex = 0
    total_token_src = 0
    total_count_unk_src = 0

    line_src = src_str

    if len(line_src) > 0:
        line_src = line_src.strip().split(" ")

        seq_src = dic_src.convert(line_src)
        unk_cnt_src = sum(dic_src.is_unk_idx(w) for w in seq_src)

        total_count_unk_src += unk_cnt_src

        total_token_src += len(seq_src)

        res.append(seq_src)
        num_ex += 1

    return res, dic_src, MakeDataInfosOneSide(total_count_unk_src,
                                              total_token_src,
                                              num_ex
                                              )

def build_dataset_one_side(src_fn, src_voc_limit=None, max_nb_ex=None, dic_src=None,
                           segmentation_type = "word"):
    if dic_src is None:
        log.info("building src_dic")
        dic_src = build_index(src_fn, src_voc_limit, max_nb_ex,
                              segmentation_type = segmentation_type)

    log.info("start indexing")

    src = codecs.open(src_fn, encoding="utf8")

    res = []

    num_ex = 0
    total_token_src = 0
    total_count_unk_src = 0
    while 1:
        if max_nb_ex is not None and num_ex >= max_nb_ex:
            break

        line_src = src.readline()

        if len(line_src) == 0:
            break

        line_src = line_src.strip().split(" ")

        seq_src = dic_src.convert(line_src)
        unk_cnt_src = sum(dic_src.is_unk_idx(w) for w in seq_src)

        total_count_unk_src += unk_cnt_src

        total_token_src += len(seq_src)

        res.append(seq_src)
        num_ex += 1

    return res, dic_src, MakeDataInfosOneSide(total_count_unk_src,
                                              total_token_src,
                                              num_ex
                                              )

def build_dataset_for_nbest_list_scoring(dic_src, nbest_list):
    res = []
    num_ex = 0
    total_token_src = 0
    total_count_unk_src = 0
    for sublist in nbest_list:
        res.append([])
        for sentence in sublist:
            seq_src = dic_src.convert(sentence)
            unk_cnt_src = sum(dic_src.is_unk_idx(w) for w in seq_src)
    
            total_count_unk_src += unk_cnt_src
    
            total_token_src += len(seq_src)
    
            res[-1].append(seq_src)
            num_ex += 1  
    return res, MakeDataInfosOneSide(total_count_unk_src,
                                              total_token_src,
                                              num_ex
                                              )
# 
# def build_dataset_one_side_from_list_of_list(src_fn, src_voc_limit=None, max_nb_ex=None, dic_src=None,
#                            segmentation_type = "word"):
#     if dic_src is None:
#         log.info("building src_dic")
#         dic_src = build_index(src_fn, src_voc_limit, max_nb_ex,
#                               segmentation_type = segmentation_type)
# 
#     log.info("start indexing")
# 
#     src = codecs.open(src_fn, encoding="utf8")
# 
#     res = []
# 
#     num_ex = 0
#     total_token_src = 0
#     total_count_unk_src = 0
#     while 1:
#         if max_nb_ex is not None and num_ex >= max_nb_ex:
#             break
# 
#         line_src = src.readline()
# 
#         if len(line_src) == 0:
#             break
# 
#         line_src = line_src.strip().split(" ")
# 
#         seq_src = dic_src.convert(line_src)
#         unk_cnt_src = sum(dic_src.is_unk_idx(w) for w in seq_src)
# 
#         total_count_unk_src += unk_cnt_src
# 
#         total_token_src += len(seq_src)
# 
#         res.append(seq_src)
#         num_ex += 1
# 
#     return res, dic_src, MakeDataInfosOneSide(total_count_unk_src,
#                                               total_token_src,
#                                               num_ex
#                                               )


class IndexingPrePostProcessor(object):
    def __init__(self, segmentation_type = "word", voc_limit = None):
        self.voc_limit = voc_limit
        self.is_initialized_ = False
        self.segmentation_type = segmentation_type
        
    def initialize(self, src_fn, max_nb_ex = None):
        log.info("building dic")
        self.indexer = build_index(src_fn, self.voc_limit, max_nb_ex,
                              segmentation_type = self.segmentation_type)
        self.is_initialized_ = True
        
    def __len__(self):
        if not self.is_initialized():
            return 0
        else:
            return len(self.indexer)
        
    def is_initialized(self):
        return self.is_initialized_
        
    def convert(self, sentence):
        assert self.is_initialized()
        segmented = segment(
            sentence, type=self.segmentation_type)
        converted = self.indexer.convert(segmented)
        unk_cnt = sum(self.indexer.is_unk_idx(w) for w in converted)
        stats = {"unk_cnt": unk_cnt, "nb_ex": 1, "token": len(converted)}
        return converted, stats
        
    @classmethod
    def make_from_serializable(cls, obj):
        res = IndexingPrePostProcessor()
        res.indexer = Indexer.make_from_serializable(obj)
        res.is_initialized_ = True
        return res
    
    def to_serializable(self):
        assert self.is_initialized()
        return self.indexer.to_serializable()
        
#     def load_and_convert(self, fn):
#         src = codecs.open(fn, encoding="utf8")
#         
#         res = []
#     
#         num_ex = 0
#         total_token_src = 0
#         total_count_unk_src = 0
#         
#         while 1:
#             if max_nb_ex is not None and num_ex >= max_nb_ex:
#                 break
#     
#             line_src = src.readline()
#             line_src, stats = self.convert(line_src.strip()) 
#         
#             total_count_unk_src += stats["unk_cnt"]
#             total_token_src += stats["token"]
#             
#             res.append((seq_src, seq_tgt))
#             num_ex += stats["nb_ex"]
# 
#         return res, dic_src, MakeDataInfos(total_count_unk_src,
#                                                 total_count_unk_tgt,
#                                                 total_token_src,
#                                                 total_token_tgt,
#                                                 num_ex
#                                                 )
    
def build_dataset_pp(src_fn, tgt_fn, src_pp, tgt_pp, max_nb_ex=None):
#                   src_voc_limit=None, tgt_voc_limit=None, max_nb_ex=None, dic_src=None, dic_tgt=None,
#                   tgt_segmentation_type="word", src_segmentation_type="word"):
    if not src_pp.is_initialized():
        log.info("building src_dic")
        src_pp.initialize(src_fn, max_nb_ex = max_nb_ex)

    if not tgt_pp.is_initialized():
        log.info("building tgt_dic")
        tgt_pp.initialize(tgt_fn, max_nb_ex = max_nb_ex)

    log.info("start indexing")

    src = codecs.open(src_fn, encoding="utf8")
    tgt = codecs.open(tgt_fn, encoding="utf8")

    res = []

    num_ex = 0
    total_token_src = 0
    total_token_tgt = 0
    total_count_unk_src = 0
    total_count_unk_tgt = 0
    while 1:
        if max_nb_ex is not None and num_ex >= max_nb_ex:
            break

        line_src = src.readline()
        line_tgt = tgt.readline()

        if len(line_src) == 0:
            assert len(line_tgt) == 0
            break

#         line_src = line_src.strip().split(" ")
        
        line_src = line_src.strip()
        line_tgt = line_tgt.strip()
        
        seq_src, stats_src = src_pp.convert(line_src) 
        total_count_unk_src += stats_src["unk_cnt"]
        total_token_src += stats_src["token"]
        
        seq_tgt, stats_tgt = tgt_pp.convert(line_tgt) 
        total_count_unk_tgt += stats_tgt["unk_cnt"]
        total_token_tgt += stats_tgt["token"]
        

        res.append((seq_src, seq_tgt))
        num_ex += 1

    return res, MakeDataInfos(total_count_unk_src,
                                                total_count_unk_tgt,
                                                total_token_src,
                                                total_token_tgt,
                                                num_ex
                                                )
#             
# def build_dataset(src_fn, tgt_fn,
#                   src_voc_limit=None, tgt_voc_limit=None, max_nb_ex=None, dic_src=None, dic_tgt=None,
#                   tgt_segmentation_type="word", src_segmentation_type="word"):
#     if dic_src is None:
#         log.info("building src_dic")
#         dic_src = build_index(src_fn, src_voc_limit, max_nb_ex,
#                               segmentation_type=src_segmentation_type)
# 
#     if dic_tgt is None:
#         log.info("building tgt_dic")
#         dic_tgt = build_index(tgt_fn, tgt_voc_limit, max_nb_ex,
#                               segmentation_type=tgt_segmentation_type)
# 
#     log.info("start indexing")
# 
#     src = codecs.open(src_fn, encoding="utf8")
#     tgt = codecs.open(tgt_fn, encoding="utf8")
# 
#     res = []
# 
#     num_ex = 0
#     total_token_src = 0
#     total_token_tgt = 0
#     total_count_unk_src = 0
#     total_count_unk_tgt = 0
#     while 1:
#         if max_nb_ex is not None and num_ex >= max_nb_ex:
#             break
# 
#         line_src = src.readline()
#         line_tgt = tgt.readline()
# 
#         if len(line_src) == 0:
#             assert len(line_tgt) == 0
#             break
# 
# #         line_src = line_src.strip().split(" ")
#         
#         line_src = segment(
#             line_src.strip(), type=src_segmentation_type)
#         
#         line_tgt = segment(
#             line_tgt.strip(), type=tgt_segmentation_type)  # .split(" ")
# 
#         seq_src = dic_src.convert(line_src)
#         unk_cnt_src = sum(dic_src.is_unk_idx(w) for w in seq_src)
# 
#         seq_tgt = dic_tgt.convert(line_tgt)
#         unk_cnt_tgt = sum(dic_tgt.is_unk_idx(w) for w in seq_tgt)
# 
#         total_count_unk_src += unk_cnt_src
#         total_count_unk_tgt += unk_cnt_tgt
# 
#         total_token_src += len(seq_src)
#         total_token_tgt += len(seq_tgt)
# 
#         res.append((seq_src, seq_tgt))
#         num_ex += 1
# 
#     return res, dic_src, dic_tgt, MakeDataInfos(total_count_unk_src,
#                                                 total_count_unk_tgt,
#                                                 total_token_src,
#                                                 total_token_tgt,
#                                                 num_ex
#                                                 )


# 
# def build_dataset_with_align_info(src_fn, tgt_fn, align_fn, 
#                                   src_voc_limit = None, tgt_voc_limit = None, max_nb_ex = None, 
#                                   dic_src = None, dic_tgt = None,
#                                   invert_alignment_links = False, add_to_valid_every = 1000,
#                                   mode = "unk_align"):
#     from aligned_parse_reader import load_aligned_corpus
#     corpus = load_aligned_corpus(
#         src_fn, tgt_fn, align_fn, skip_empty_align=True, invert_alignment_links=invert_alignment_links)
# 
#     # first find the most frequent words
#     log.info("computing restricted vocabulary")
#     counts_src = collections.defaultdict(int)
#     counts_tgt = collections.defaultdict(int)
#     for num_ex, (sentence_src, sentence_tgt, alignment) in enumerate(corpus):
#         if num_ex % add_to_valid_every == 0:
#             continue
# 
#         if max_nb_ex is not None and num_ex >= max_nb_ex:
#             break
#         for pos, w in enumerate(sentence_src):
#             counts_src[w] += 1
#         for w in sentence_tgt:
#             counts_tgt[w] += 1
#     sorted_counts_src = sorted(
#         counts_src.items(), key=operator.itemgetter(1), reverse=True)
#     sorted_counts_tgt = sorted(
#         counts_tgt.items(), key=operator.itemgetter(1), reverse=True)
# 
#     dic_src = Indexer()
#     dic_src.assign_index_to_voc((w for w, _ in sorted_counts_src[
#                                 :src_voc_limit]), all_should_be_new=True)
# 
#     dic_tgt = Indexer()
# 
#     dic_tgt.assign_index_to_voc((w for w, _ in sorted_counts_tgt[:tgt_voc_limit]), all_should_be_new = True)
#     
#     if mode == "all_align":
#         dic_src.finalize()
#         dic_tgt.finalize()
#     
#     log.info("computed restricted vocabulary")
# 
# #     src_unk_tag = "#S_UNK_%i#!"
# #     tgt_unk_tag = "#T_UNK_%i#!"
# 
#     corpus = load_aligned_corpus(
#         src_fn, tgt_fn, align_fn, skip_empty_align=True, invert_alignment_links=invert_alignment_links)
# 
#     total_token_src = 0
#     total_token_tgt = 0
#     total_count_unk_src = [0]
#     total_count_unk_tgt = [0]
#     res = []
#     valid = []
#     fertility_counts = collections.defaultdict(
#         lambda: collections.defaultdict(int))
#     for num_ex, (sentence_src, sentence_tgt, alignment) in enumerate(corpus):
#         if max_nb_ex is not None and num_ex >= max_nb_ex:
#             break
#         local_fertilities = {}
#         local_alignments = {}
#         for left, right in alignment:
#             for src_pos in left:
#                 local_fertilities[src_pos] = len(right)
#             for tgt_pos in right:
#                 assert tgt_pos not in local_alignments
#                 local_alignments[tgt_pos] = left[0]
#     
#         if mode == "unk_align":
#             def give_fertility(pos, w):
#                 fertility = local_fertilities.get(pos, 0)
#                 fertility_counts[w][fertility] += 1
#                 total_count_unk_src[0] += 1
#                 return fertility
#             
#             def give_alignment(pos, w):
#                 total_count_unk_tgt[0] += 1
#                 aligned_pos = local_alignments.get(pos, -1)
#                 return aligned_pos
#             
#             seq_idx_src = dic_src.convert_and_update_unk_tags(sentence_src, give_unk_label = give_fertility)
#             total_token_src += len(seq_idx_src)
#             
#             seq_idx_tgt = dic_tgt.convert_and_update_unk_tags(sentence_tgt, give_unk_label = give_alignment)
#             total_token_tgt += len(seq_idx_tgt)
#             
#         elif mode == "all_align":
#             def give_fertility(pos, w):
#                 fertility = local_fertilities.get(pos, 0)
#                 fertility_counts[w][fertility] += 1
#                 return fertility
#             
#             def give_alignment(pos):
#                 aligned_pos = local_alignments.get(pos, -1)
#                 return aligned_pos
#             
#             seq_src = dic_src.convert(sentence_src)
#             unk_cnt_src = sum(dic_src.is_unk_idx(w) for w in seq_src)
#             
#             seq_tgt = dic_tgt.convert(sentence_tgt)
#             unk_cnt_tgt = sum(dic_tgt.is_unk_idx(w) for w in seq_tgt)
#     
#             total_count_unk_src[0] += unk_cnt_src
#             total_count_unk_tgt[0] += unk_cnt_tgt
#             
#             total_token_src += len(seq_src)
#             total_token_tgt += len(seq_tgt)
#             
#             seq_idx_src = []
#             for pos in range(len(seq_src)):
#                 w = seq_src[pos]
#                 seq_idx_src.append( (w, give_fertility(pos, w)) )
#                 
#             seq_idx_tgt = []
#             for pos in range(len(seq_tgt)):
#                 w = seq_tgt[pos]
#                 seq_idx_tgt.append( (w, give_alignment(pos)) )
#             
#         else:
#             assert False
#         
#         if num_ex % add_to_valid_every == 0:
#             valid.append((seq_idx_src, seq_idx_tgt))
#         else:
#             res.append((seq_idx_src, seq_idx_tgt))
#     
#     if mode == "unk_align":
#         src_unk_voc_to_fertility = {}
#         for w in fertility_counts:
#             most_common_fertility = sorted(fertility_counts[w].items(), key = operator.itemgetter(1), reverse = True)[0][0]
#             src_unk_voc_to_fertility[w] = most_common_fertility
#             
#         dic_src.add_unk_label_dictionary(src_unk_voc_to_fertility)
#         
#         dic_tgt.finalize()
#         dic_src.finalize()
#     
#     return res, valid, dic_src, dic_tgt, MakeDataInfos(total_count_unk_src[0], 
#                                                 total_count_unk_tgt[0], 
#                                                 total_token_src, 
#                                                 total_token_tgt, 
#                                                 num_ex
#                                                 )
#     return res, valid, dic_src, dic_tgt, MakeDataInfos(total_count_unk_src[0],
#                                                        total_count_unk_tgt[0],
#                                                        total_token_src,
#                                                        total_token_tgt,
#                                                        num_ex
#                                                        )

def do_make_data(config):
    save_prefix_dir, save_prefix_fn = os.path.split(config.save_prefix)
    ensure_path(save_prefix_dir)

    config_fn = config.save_prefix + ".data.config"
    voc_fn = config.save_prefix + ".voc"
    data_fn = config.save_prefix + ".data.json.gz"
#     valid_data_fn = config.save_prefix + "." + config.model + ".valid.data.npz"

    already_existing_files = []
    for filename in [config_fn, voc_fn, data_fn]:  # , valid_data_fn]:
        if os.path.exists(filename):
            already_existing_files.append(filename)
    if len(already_existing_files) > 0:
        print "Warning: existing files are going to be replaced: ",  already_existing_files
        raw_input("Press Enter to Continue")

    if config.use_voc is not None:
        log.info("loading voc from %s" % config.use_voc)
        src_voc, tgt_voc = json.load(open(config.use_voc))
        src_pp = IndexingPrePostProcessor.make_from_serializable(src_voc)
        tgt_pp = IndexingPrePostProcessor.make_from_serializable(tgt_voc)
    else:
        src_pp = IndexingPrePostProcessor(segmentation_type = config.src_segmentation_type, voc_limit = config.src_voc_size)
        tgt_pp = IndexingPrePostProcessor(segmentation_type = config.tgt_segmentation_type, voc_limit = config.tgt_voc_size)
    
    def load_data(src_fn, tgt_fn, max_nb_ex=None):

        training_data, make_data_infos = build_dataset_pp(
            src_fn, tgt_fn, src_pp, tgt_pp,
            max_nb_ex=max_nb_ex)

        log.info("%i sentences loaded" % make_data_infos.nb_ex)
        log.info("size dic src: %i" % len(src_pp))
        log.info("size dic tgt: %i" % len(tgt_pp))

        log.info("#tokens src: %i   of which %i (%f%%) are unknown" % (make_data_infos.total_token_src,
                                                                       make_data_infos.total_count_unk_src,
                                                                       float(make_data_infos.total_count_unk_src * 100) /
                                                                       make_data_infos.total_token_src))

        log.info("#tokens tgt: %i   of which %i (%f%%) are unknown" % (make_data_infos.total_token_tgt,
                                                                       make_data_infos.total_count_unk_tgt,
                                                                       float(make_data_infos.total_count_unk_tgt * 100) /
                                                                       make_data_infos.total_token_tgt))

        return training_data



    log.info("loading training data from %s and %s" %
             (config.src_fn, config.tgt_fn))
    training_data = load_data(config.src_fn, config.tgt_fn, max_nb_ex=config.max_nb_ex)

    test_data = None
    if config.test_src is not None:
        log.info("loading test data from %s and %s" %
                 (config.test_src, config.test_tgt))
        test_data = load_data(
            config.test_src, config.test_tgt)


    dev_data = None
    if config.dev_src is not None:
        log.info("loading dev data from %s and %s" %
                 (config.dev_src, config.dev_tgt))
        dev_data = load_data(
            config.dev_src, config.dev_tgt)


#     if config.shuffle:
#         log.info("shuffling data")
#         if config.enable_fast_shuffle:
#             shuffle_in_unison_faster(data_input, data_target)
#         else:
#             data_input, data_target = shuffle_in_unison(data_input, data_target)
    log.info("saving config to %s" % config_fn)
    config.save_to(config_fn)
#     json.dump(config.__dict__, open(config_fn, "w"),
#               indent=2, separators=(',', ': '))

    log.info("saving voc to %s" % voc_fn)
    json.dump([src_pp.to_serializable(), tgt_pp.to_serializable()],
              open(voc_fn, "w"), indent=2, separators=(',', ': '))

    log.info("saving train_data to %s" % data_fn)
    data_all = {"train": training_data}
    if test_data is not None:
        data_all["test"] = test_data
    if dev_data is not None:
        data_all["dev"] = dev_data

    json.dump(data_all, gzip.open(data_fn, "wb"),
              indent=2, separators=(',', ': '))
#     fh5 = h5py.File(args.save_data_to_hdf5, 'w')
#     train_grp = fh5.create_group("train")
#     train_grp.attrs["size"] = len(training_data)
#     for i in range(len(training_data)):
#         train_grp.create_dataset("s%i"%i, data = training_data[i][0], compression="gzip")
#         train_grp.create_dataset("t%i"%i, data = training_data[i][1], compression="gzip")

#     if args.add_to_valid_set_every:
#         log.info("saving valid_data to %s"%valid_data_fn)
#         np.savez_compressed(open(valid_data_fn, "wb"), data_input = data_input_valid, data_target = data_target_valid)


# def do_make_data(config):
#     save_prefix_dir, save_prefix_fn = os.path.split(config.save_prefix)
#     ensure_path(save_prefix_dir)
# 
#     config_fn = config.save_prefix + ".data.config"
#     voc_fn = config.save_prefix + ".voc"
#     data_fn = config.save_prefix + ".data.json.gz"
# #     valid_data_fn = config.save_prefix + "." + config.model + ".valid.data.npz"
# 
#     already_existing_files = []
#     for filename in [config_fn, voc_fn, data_fn]:  # , valid_data_fn]:
#         if os.path.exists(filename):
#             already_existing_files.append(filename)
#     if len(already_existing_files) > 0:
#         print "Warning: existing files are going to be replaced: ",  already_existing_files
#         raw_input("Press Enter to Continue")
# 
#     src_pp = IndexingPrePostProcessor(segmentation_type = config.src_segmentation_type, voc_limit = config.src_voc_size)
#     tgt_pp = IndexingPrePostProcessor(segmentation_type = config.tgt_segmentation_type, voc_limit = config.tgt_voc_size)
#     
#     def load_data(src_fn, tgt_fn, max_nb_ex=None, dic_src=None, dic_tgt=None, align_fn=None):
# 
#         if align_fn is not None:
#             raise NotImplemented() #TODO: not used for now, so not updating this part for now
# #             log.info("making training data with alignment")
# #             training_data, valid_data, dic_src, dic_tgt, make_data_infos = build_dataset_with_align_info(
# #                                             src_fn, tgt_fn, align_fn, src_voc_limit = config.src_voc_size, 
# #                                             tgt_voc_limit = config.tgt_voc_size, max_nb_ex = max_nb_ex, 
# #                                             dic_src = dic_src, dic_tgt = dic_tgt, mode = config.mode_align)
#         else:
#             training_data, dic_src, dic_tgt, make_data_infos = build_dataset(
#                 src_fn, tgt_fn, src_voc_limit=config.src_voc_size,
#                 tgt_voc_limit=config.tgt_voc_size, max_nb_ex=max_nb_ex,
#                 dic_src=dic_src, dic_tgt=dic_tgt,
#                 tgt_segmentation_type=config.tgt_segmentation_type,
#                 src_segmentation_type=config.src_segmentation_type)
#             valid_data = None
# 
#         log.info("%i sentences loaded" % make_data_infos.nb_ex)
#         if valid_data is not None:
#             log.info("valid set size:%i sentences" % len(valid_data))
#         log.info("size dic src: %i" % len(dic_src))
#         log.info("size dic tgt: %i" % len(dic_tgt))
# 
#         log.info("#tokens src: %i   of which %i (%f%%) are unknown" % (make_data_infos.total_token_src,
#                                                                        make_data_infos.total_count_unk_src,
#                                                                        float(make_data_infos.total_count_unk_src * 100) /
#                                                                        make_data_infos.total_token_src))
# 
#         log.info("#tokens tgt: %i   of which %i (%f%%) are unknown" % (make_data_infos.total_token_tgt,
#                                                                        make_data_infos.total_count_unk_tgt,
#                                                                        float(make_data_infos.total_count_unk_tgt * 100) /
#                                                                        make_data_infos.total_token_tgt))
# 
#         return training_data, valid_data, dic_src, dic_tgt
# 
#     dic_src = None
#     dic_tgt = None
#     if config.use_voc is not None:
#         log.info("loading voc from %s" % config.use_voc)
#         src_voc, tgt_voc = json.load(open(config.use_voc))
#         dic_src = Indexer.make_from_serializable(src_voc)
#         dic_tgt = Indexer.make_from_serializable(tgt_voc)
# 
#     log.info("loading training data from %s and %s" %
#              (config.src_fn, config.tgt_fn))
#     training_data, valid_data, dic_src, dic_tgt = load_data(config.src_fn, config.tgt_fn, max_nb_ex=config.max_nb_ex,
#                                                             dic_src=dic_src, dic_tgt=dic_tgt, align_fn=config.align_fn)
# 
#     test_data = None
#     if config.test_src is not None:
#         log.info("loading test data from %s and %s" %
#                  (config.test_src, config.test_tgt))
#         test_data, _, test_dic_src, test_dic_tgt = load_data(
#             config.test_src, config.test_tgt, dic_src=dic_src, dic_tgt=dic_tgt)
# 
#         assert test_dic_src is dic_src
#         assert test_dic_tgt is dic_tgt
# 
#     dev_data = None
#     if config.dev_src is not None:
#         log.info("loading dev data from %s and %s" %
#                  (config.dev_src, config.dev_tgt))
#         dev_data, _, dev_dic_src, dev_dic_tgt = load_data(
#             config.dev_src, config.dev_tgt, dic_src=dic_src, dic_tgt=dic_tgt)
# 
#         assert dev_dic_src is dic_src
#         assert dev_dic_tgt is dic_tgt
# 
# #     if config.shuffle:
# #         log.info("shuffling data")
# #         if config.enable_fast_shuffle:
# #             shuffle_in_unison_faster(data_input, data_target)
# #         else:
# #             data_input, data_target = shuffle_in_unison(data_input, data_target)
#     log.info("saving config to %s" % config_fn)
#     config.save_to(config_fn)
# #     json.dump(config.__dict__, open(config_fn, "w"),
# #               indent=2, separators=(',', ': '))
# 
#     log.info("saving voc to %s" % voc_fn)
#     json.dump([dic_src.to_serializable(), dic_tgt.to_serializable()],
#               open(voc_fn, "w"), indent=2, separators=(',', ': '))
# 
#     log.info("saving train_data to %s" % data_fn)
#     data_all = {"train": training_data}
#     if test_data is not None:
#         data_all["test"] = test_data
#     if dev_data is not None:
#         data_all["dev"] = dev_data
#     if valid_data is not None:
#         data_all["valid"] = valid_data
# 
#     json.dump(data_all, gzip.open(data_fn, "wb"),
#               indent=2, separators=(',', ': '))
# #     fh5 = h5py.File(args.save_data_to_hdf5, 'w')
# #     train_grp = fh5.create_group("train")
# #     train_grp.attrs["size"] = len(training_data)
# #     for i in range(len(training_data)):
# #         train_grp.create_dataset("s%i"%i, data = training_data[i][0], compression="gzip")
# #         train_grp.create_dataset("t%i"%i, data = training_data[i][1], compression="gzip")
# 
# #     if args.add_to_valid_set_every:
# #         log.info("saving valid_data to %s"%valid_data_fn)
# #         np.savez_compressed(open(valid_data_fn, "wb"), data_input = data_input_valid, data_target = data_target_valid)

