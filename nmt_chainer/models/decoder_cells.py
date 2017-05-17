#!/usr/bin/env python
"""decoder_cells.py: Implementation of RNNSearch in Chainer"""
__author__ = "Fabien Cromieres"
__license__ = "undecided"
__version__ = "1.0"
__email__ = "fabien.cromieres@gmail.com"
__status__ = "Development"

import numpy as np
import chainer
from chainer import cuda, Variable
from chainer import Link, Chain, ChainList
import chainer.functions as F
import chainer.links as L
import random

import rnn_cells
from nmt_chainer.utilities.utils import ortho_init, minibatch_sampling

from nmt_chainer.utilities.constant_batch_mul import batch_matmul_constant, matmul_constant

from attention import AttentionModule, PointerMechanism

import logging
logging.basicConfig()
log = logging.getLogger("rnns:dec")
log.setLevel(logging.INFO)

#################################################################################################
# Loss computation
#

def elem_wise_sce(logits, targets):
    normalized_logits = F.log_softmax(logits)
    return F.select_item(normalized_logits, targets)

def softmax_cross_entropy(logits, targets, per_sentence=False):
    if per_sentence:
        return elem_wise_sce(logits, targets)
    else:
        return F.softmax_cross_entropy(logits, targets)

def make_MSE_cross_entropy(emb):
    def MSE_cross_entropy(logits, targets, per_sentence=False):
        if per_sentence:
            raise NotImplemented
        targets_emb = emb(targets)
        targets_emb.unchain_backward()
#         return F.mean_squared_error(logits, targets_emb)
        return F.mean_absolute_error(logits, targets_emb)
    return MSE_cross_entropy

def make_pointer_loss(V, xp, device):
    with device:
        Vm_array = xp.array([V-1], dtype = xp.int32)
        m1_array = xp.array([-1], dtype = xp.int32)
        
    def pointer_loss(logits, targets, per_sentence=False):
        logits_v, logits_p = logits
        mb_size = targets.data.shape[0]
        broadcasted_Vm = xp.broadcast_to(Vm_array, (mb_size,))
        broadcasted_m1 = xp.broadcast_to(m1_array, (mb_size,))
        caped_target = F.where(targets <= broadcasted_Vm, targets, broadcasted_m1)
        ptr_value = F.maximum(targets - broadcasted_Vm, 0)
        if per_sentence:
            v_mask = targets <= Vm_array
            sce_p = elem_wise_sce(logits_p, ptr_value)
            sce_v = elem_wise_sce(logits_v, caped_target) * v_mask
        else:
            sce_p = F.softmax_cross_entropy(logits_p, ptr_value)
            sce_v = F.softmax_cross_entropy(logits_v, caped_target, normalize=True)
        return sce_p + sce_v
    return pointer_loss

##################################################################################
# Logit Classes
#

class SimpleLogit(object):
    def __init__(self, logit):
        self.logit = logit
        self.xp = chainer.cuda.get_array_module(logit.data)
        self.device = chainer.cuda.get_device(logit.data)
        
    @classmethod
    def combine(cls, logits_list, prob_space_combination=False):
        assert len(logits_list) >= 1
        assert all(isinstance(lgt, SimpleLogit) for lgt in logits_list)
        assert all(lgt.logit.shape == logits_list[0].logit.shape for lgt in logits_list[1:])
        xp = chainer.cuda.get_array_module(logits_list[0].logit.data)
        if len(logits_list) == 1:
            return xp.log(F.softmax(logits_list[0].logit).data)
        else:
            combined_scores = xp.zeros((logits_list[0].logit.data.shape), dtype=xp.float32)
        
            if not prob_space_combination:
                for logits in logits_list:
                    combined_scores += xp.log(F.softmax(logits.logit).data)
                combined_scores /= len(logits_list)
            else:
                for logits in logits_list:
                    combined_scores += F.softmax(logits.logit).data
                combined_scores /= len(logits_list)
                combined_scores = xp.log(combined_scores)
            return combined_scores
        
    def get_argmax(self, required_mb_size=None):
        self.xp.argmax(self.logit.data[:required_mb_size], axis=1).astype(self.xp.int32)
        
    def compute_loss(self, targets, per_sentence=False):
        return softmax_cross_entropy(self.logit, targets, per_sentence=per_sentence)
        
    def sample(self):
        # TODO: rewrite with gumbel
        probs = F.softmax(self.logit)
        with self.device:
            if self.xp != np:
                probs_data = cuda.to_cpu(probs.data)
            else:
                probs_data = probs.data
            curr_idx = minibatch_sampling(probs_data)
            if self.xp != np:
                curr_idx = cuda.to_gpu(curr_idx.astype(np.int32))
            else:
                curr_idx = curr_idx.astype(np.int32)
        return curr_idx
    
    def compute_log_prob(self, curr_idx):
        mb_size = curr_idx.shape[0]
        probs = F.softmax(self.logit)
        score = np.log(cuda.to_cpu(probs.data)[np.arange(mb_size), cuda.to_cpu(curr_idx)])
        return score
        
class PointerLogit(object):
    def __init__(self, logit, logit_ptr):
        self.logit = logit
        self.logit_ptr = logit_ptr
       
       
    @classmethod
    def combine(cls, logits_list, prob_space_combination=False):
        assert len(logits_list) >= 1
        assert all(isinstance(lgt, SimpleLogit) for lgt in logits_list)
        assert all(lgt.logit.shape == logits_list[0].logit.shape for lgt in logits_list[1:])
        assert all(lgt.logit_ptr.shape == logits_list[0].logit_ptr.shape for lgt in logits_list[1:])
        mb, Vp = logits_list[0].logit.data.shape
        mb2, psize = logits_list[0].logit_ptr.data.shape
        assert mb == mb2
        xp = chainer.cuda.get_array_module(logits_list[0].logit.data)
        
        combined_scores = xp.zeros((mb, Vp + psize -1), dtype=xp.float32)
        if not prob_space_combination:
            for logits in logits_list:
                combined_scores[:,:Vp] += xp.log(F.softmax(logits.logit).data)
            combined_scores /= len(logits_list)
        else:
            for logits in logits_list:
                combined_scores[:,:Vp] += F.softmax(logits.logit).data
            combined_scores /= len(logits_list)
            combined_scores = xp.log(combined_scores)
        return combined_scores
        
################################################################################
# ConditionalizedDecoderCell
#
        
class ConditionalizedDecoderCell(object):
    """
        Decoding cell conditionalized on a given input sentence.
        Constructor parameters:
            decoder_chain is a decoder model
            compute_ctxt is a function computing the context vector from the decoder state
                        (it is normally generated by an attention model)
                        
        Main public methods:
            get_initial_logits return the logits giving the probability for the first word of the translation
            __call__ compute the next decoder state and the next logits
    
    """
    def __init__(self, decoder_chain, compute_ctxt, mb_size, noise_on_prev_word=False,
                 mode="test", lexicon_probability_matrix=None, lex_epsilon=1e-3, demux=False):
        self.decoder_chain = decoder_chain
        self.compute_ctxt = compute_ctxt
        self.noise_on_prev_word = noise_on_prev_word
        self.mode = mode
        self.lexicon_probability_matrix = lexicon_probability_matrix
        self.lex_epsilon = lex_epsilon

        self.mb_size = mb_size
        self.demux = demux

        self.xp = decoder_chain.xp

        if noise_on_prev_word:
            self.noise_mean = self.xp.ones((mb_size, self.decoder_chain.Eo), dtype=self.xp.float32)
            self.noise_lnvar = self.xp.zeros((mb_size, self.decoder_chain.Eo), dtype=self.xp.float32)

    def advance_state(self, previous_states, prev_y):
        current_mb_size = prev_y.data.shape[0]
        assert self.mb_size is None or current_mb_size <= self.mb_size

        if current_mb_size < len(previous_states[0].data):
            truncated_states = [None] * len(previous_states)
            for num_state in xrange(len(previous_states)):
                truncated_states[num_state], _ = F.split_axis(
                    previous_states[num_state], (current_mb_size,), 0)
            previous_states = tuple(truncated_states)

        output_state = previous_states[-1]
        if self.decoder_chain.use_goto_attention:
            ci, attn = self.compute_ctxt(output_state, prev_y)
        else:
            ci, attn = self.compute_ctxt(output_state)
        concatenated = F.concat((prev_y, ci))

        new_states = self.decoder_chain.gru(previous_states, concatenated, mode=self.mode)
        return new_states, concatenated, attn

    def compute_logits(self, new_states, concatenated, attn):
        new_output_state = new_states[-1]

        all_concatenated = F.concat((concatenated, new_output_state))
        logits = self.decoder_chain.lin_o(self.decoder_chain.maxo(all_concatenated))

        if self.lexicon_probability_matrix is not None:
            current_mb_size = new_output_state.data.shape[0]
            assert self.mb_size is None or current_mb_size <= self.mb_size
            lexicon_probability_matrix = self.lexicon_probability_matrix[:current_mb_size]

            # Just making sure data shape is as expected
            attn_mb_size, max_source_length_attn = attn.data.shape
            assert attn_mb_size == current_mb_size
            lex_mb_size, max_source_length_lexicon, v_size_lexicon = lexicon_probability_matrix.shape
            assert max_source_length_lexicon == max_source_length_attn
            assert logits.data.shape == (current_mb_size, v_size_lexicon)

            if self.demux:
                assert lex_mb_size == 1
                weighted_lex_probs = F.reshape(
                    matmul_constant(attn, lexicon_probability_matrix.reshape(lexicon_probability_matrix.shape[1],
                                                                             lexicon_probability_matrix.shape[2])),
                    logits.data.shape)
            else:
                assert lex_mb_size == current_mb_size

    #                 weighted_lex_probs = F.reshape(
    #                         F.batch_matmul(attn, ConstantFunction(lexicon_probability_matrix)(), transa = True),
    #                                                logits.data.shape)

                weighted_lex_probs = F.reshape(
                    batch_matmul_constant(attn, lexicon_probability_matrix, transa=True),
                    logits.data.shape)

            logits += F.log(weighted_lex_probs + self.lex_epsilon)
            
        if self.decoder_chain.pointer_mechanism:
            logits_ptr = self.decoder_chain.ptr_mec(all_concatenated)
            return PointerLogit(logits, logits_ptr)
        else:
            return SimpleLogit(logits)

    def advance_one_step(self, previous_states, prev_y):

        if self.noise_on_prev_word:
            current_mb_size = prev_y.data.shape[0]
            assert self.mb_size is None or current_mb_size <= self.mb_size
            prev_y = prev_y * F.gaussian(Variable(self.noise_mean[:current_mb_size], volatile="auto"),
                                         Variable(self.noise_lnvar[:current_mb_size], volatile="auto"))

        new_states, concatenated, attn = self.advance_state(previous_states, prev_y)

        logits = self.compute_logits(new_states, concatenated, attn)

        return new_states, logits, attn

    def get_initial_logits(self, mb_size=None):
        if mb_size is None:
            mb_size = self.mb_size
        assert mb_size is not None

        previous_states = self.decoder_chain.gru.get_initial_states(mb_size)

        prev_y = F.broadcast_to(self.decoder_chain.bos_embeding, (mb_size, self.decoder_chain.Eo))

        new_states, logits, attn = self.advance_one_step(previous_states, prev_y)

        return new_states, logits, attn

    def __call__(self, prev_states, inpt, is_soft_inpt=False, from_emb=False):
        if is_soft_inpt:
            assert not from_emb
            assert not self.decoder_chain.pointer_mechanism
            prev_y = F.matmul(inpt, self.decoder_chain.emb.W)
        elif from_emb:
            assert not self.decoder_chain.pointer_mechanism
            prev_y = self.decoder_chain.emb.from_emb(inpt)
        else:
            prev_y = self.decoder_chain.get_prev_word_embedding(inpt)
            
        new_states, logits, attn = self.advance_one_step(prev_states, prev_y)

        return new_states, logits, attn

# class ConditionalizedDecoderCellCharEnc(ConditionalizedDecoderCell):
#     def __init__(self, decoder_chain, compute_ctxt, mb_size, noise_on_prev_word=False,
#                  mode="test", lexicon_probability_matrix=None, lex_epsilon=1e-3, demux=False):
#         super(ConditionalizedDecoderCellCharEnc, self).__init__(decoder_chain, compute_ctxt, mb_size, 
#                                                                 noise_on_prev_word=noise_on_prev_word,
#                  mode=mode, lexicon_probability_matrix=lexicon_probability_matrix, lex_epsilon=lex_epsilon, demux=demux)
   
class ChainLinks(ChainList):
    def __init__(self, *links):
        super(ChainLinks, self).__init__(*links)
       
    def __call__(self, x):
        for link in self.children():
            x = link(x)
        return x
       
       
       
class MLP(ChainList):
    def __init__(self, layer_sizes, activ = F.relu):
        super(MLP, self).__init__()
        self.activ = activ
        self.nb_layers = len(layer_sizes) - 1
        for num_layer in range(self.nb_layers):
            in_size = layer_sizes[num_layer]
            out_size = layer_sizes[num_layer + 1]
            self.add_link(L.Linear(in_size, out_size))
            
    def __call__(self, x):
        for num_layer in range(self.nb_layers):
            x = self[num_layer](x)
            if num_layer < self.nb_layers -1:
                x = self.activ(x)
        return x
        
        
class CharEncEmbedId(Chain):
    def __init__(self, emb, layer_sizes):
        emb_size = emb.W.data.shape[1]
        super(CharEncEmbedId, self).__init__(
            mlp = MLP( (emb_size,) + layer_sizes)
            )
        self.emb = emb
        
    def to_gpu(self, dev=None):
        super(CharEncEmbedId, self).to_gpu(dev)
        self.emb = self.emb.to_gpu(dev)
        
    def __call__(self, x):
        x_emb = self.emb(x)
        x_emb.unchain_backward()
        return self.mlp(x_emb)
    
    def from_emb(self, x_emb):
        return self.mlp(x_emb)

#############################################################################
# Computing Loss      



def loss_updater(logits, targets, loss, total_nb_predictions, per_sentence=False,
                 loss_computer=softmax_cross_entropy):
    xp = chainer.cuda.get_array_module(logits["logits"].data)
    if per_sentence:
        total_local_loss = logits.compute_loss(targets, per_sentence=True) #F.select_item(normalized_logits, targets)
        if loss is not None and total_local_loss.data.shape[0] != loss.data.shape[0]:
            assert total_local_loss.data.shape[0] < loss.data.shape[0]
            total_local_loss = F.concat(
                (total_local_loss,
                 Variable(xp.zeros(loss.data.shape[0] - total_local_loss.data.shape[0],
                                        dtype=xp.float32), volatile="auto")),
                axis=0)
    else:
        local_loss = logits.compute_loss(targets, per_sentence=False)
        nb_predictions = targets.data.shape[0]
        total_local_loss = local_loss * nb_predictions
        total_nb_predictions += nb_predictions
        
    loss = total_local_loss if loss is None else loss + total_local_loss
        
    return loss, total_nb_predictions


def compute_loss_from_decoder_cell(cell, targets, use_previous_prediction=0,
                                   raw_loss_info=False, per_sentence=False, keep_attn=False,
                                   use_soft_prediction_feedback=False, 
                                   use_gumbel_for_soft_predictions=False,
                                   temperature_for_soft_predictions=1.0,
                                   loss_computer=softmax_cross_entropy):
    """
        Function that compute a loss given a target output and a conditionalized decoder cell.
        
        cell is an object of the class ConditionalizedDecoderCell (or a class with a similar interface for the 
                    methods get_initial_logits and __call__)
                    
        targets is the target output, as a chainer Variable/ array of int32 
    """
    loss = None
    attn_list = []

    mb_size = targets[0].data.shape[0]
    assert cell.mb_size is None or cell.mb_size == mb_size
    states, logits, attn = cell.get_initial_logits(mb_size)

    total_nb_predictions = 0

    for i in xrange(len(targets)):
        if keep_attn:
            attn_list.append(attn)

        loss, total_nb_predictions = loss_updater(logits, targets[i], loss, total_nb_predictions, per_sentence=per_sentence,
                                                  loss_computer=loss_computer)

        if i >= len(targets) - 1:  # skipping generation of last states as unneccessary
            break

        current_mb_size = targets[i].data.shape[0]
        required_next_mb_size = targets[i + 1].data.shape[0]

        if use_soft_prediction_feedback:
            logits_for_soft_predictions = logits.logit
            if required_next_mb_size < current_mb_size:
                logits_for_soft_predictions, _ = F.split_axis(logits_for_soft_predictions, (required_next_mb_size,), 0)
            if use_gumbel_for_soft_predictions:
                logits_for_soft_predictions = logits_for_soft_predictions + cell.xp.random.gumbel(size=logits_for_soft_predictions.data.shape).astype(cell.xp.float32)
            if temperature_for_soft_predictions != 1.0:
                logits_for_soft_predictions = logits_for_soft_predictions/temperature_for_soft_predictions
                
            previous_word = F.softmax(logits_for_soft_predictions)
        else:
            if use_previous_prediction > 0 and random.random() < use_previous_prediction:
                previous_word = Variable(logits.get_argmax(required_next_mb_size), volatile="auto")
            else:
                if required_next_mb_size < current_mb_size:
                    previous_word, _ = F.split_axis(targets[i], (required_next_mb_size,), 0)
                    current_mb_size = required_next_mb_size
                else:
                    previous_word = targets[i]

        states, logits, attn = cell(states, previous_word, is_soft_inpt=use_soft_prediction_feedback)

    if raw_loss_info:
        return (loss, total_nb_predictions), attn_list
    else:
        loss = loss / total_nb_predictions
        return loss, attn_list

#############################################################################
# Sampling 

def sample_from_decoder_cell(cell, nb_steps, best=False, keep_attn_values=False,
                             need_score=False):
    """
        Function that sample an output from a conditionalized decoder cell
    """
    states, logits, attn = cell.get_initial_logits()

    score = 0
    sequences = []
    attn_list = []

    for _ in xrange(nb_steps):
        if keep_attn_values:
            attn_list.append(attn)

        if best:
            curr_idx = logits.get_argmax()
        else:
            curr_idx = logits.sample()
            
        if need_score:
            score = score + logits.compute_log_prob(curr_idx)
        sequences.append(curr_idx)

        previous_word = Variable(curr_idx, volatile="auto")

        states, logits, attn = cell(states, previous_word)

    return sequences, score, attn_list

def sample_from_decoder_cell_charenc(cell, nb_steps, keep_attn_values=False):

    states, logits, attn = cell.get_initial_logits()

    sequences = []
    attn_list = []

    for _ in xrange(nb_steps):
        if keep_attn_values:
            attn_list.append(attn)

        sequences.append(logits)

        states, logits, attn = cell(states, logits, from_emb=True)

    return sequences, attn_list


class Decoder(Chain):
    """ Decoder for RNNSearch.
        The __call_ takes 3 required parameters: fb_concat, targets, mask.

        fb_concat should be the result of a call to Encoder.

        targets is a python list of chainer variables of type int32 and of variable shape (n,)
            the values n should be decreasing:
                i < j => targets[i].data.shape[0] >= targets[j].data.shape[0]
            targets[i].data[j] is the jth elements of the ith sequence in the minibatch
            all this imply that the sequences of the minibatch should be sorted from longest to shortest

        mask is as in the description of Encoder.

        * it is up to the user to add an EOS token to the data.

        Return a loss and the attention model values
    """

    def __init__(self, Vo, Eo, Ho, Ha, Hi, Hl, attn_cls=AttentionModule, init_orth=False,
                 cell_type=rnn_cells.LSTMCell, use_goto_attention=False, char_enc_emb = None,
                 mlp_logits=None, pointer_mechanism=False):

        if isinstance(cell_type, (str, unicode)):
            cell_type = rnn_cells.create_cell_model_from_string(cell_type)

        gru = cell_type(Eo + Hi, Ho)

        log.info("constructing decoder [%r]" % (cell_type,))

        if char_enc_emb is None:
            emb = L.EmbedID(Vo, Eo)
            self.char_enc_emb = None
        else:
            v_size_char_enc, enc_size_char_enc = char_enc_emb.shape
            char_emb_tgt = L.EmbedID(v_size_char_enc + 2, enc_size_char_enc)
            assert char_emb_tgt.W.data.shape == (v_size_char_enc + 2, enc_size_char_enc)
            char_emb_tgt.W.data[:-2] = char_enc_emb
            log.info("using last two voc for unk and eos")
            char_emb_tgt.W.data[-2:] = char_enc_emb[-2:] 
            emb = CharEncEmbedId(char_emb_tgt, (Eo, Eo))
            self.char_enc_emb = char_emb_tgt
            Vo = enc_size_char_enc

        if use_goto_attention:
            log.info("using 'Goto' attention")
            
            
        if mlp_logits is not None:
            log.info("using 'mlp_logits %r", ((Eo + Hi + Ho,) + mlp_logits,))
            maxo = ChainLinks(MLP((Eo + Hi + Ho,) + mlp_logits), L.Maxout(mlp_logits[-1], Hl, 2))
        else:
            maxo=L.Maxout(Eo + Hi + Ho, Hl, 2)
            
        super(Decoder, self).__init__(
            emb=emb,
            #             gru = L.GRU(Ho, Eo + Hi),

            gru=gru,

            maxo=maxo,
            lin_o=L.Linear(Hl, Vo, nobias=False),

            attn_module=attn_cls(Hi, Ha, Ho, init_orth=init_orth, 
                                 prev_word_embedding_size = Eo if use_goto_attention else None)
        )
        
#         self.add_param("initial_state", (1, Ho))
        self.add_param("bos_embeding", (1, Eo))

        self.pointer_mechanism = pointer_mechanism
        if self.pointer_mechanism:
            self.add_link("ptr_mec", PointerMechanism())

        self.use_goto_attention = use_goto_attention
        self.Hi = Hi
        self.Ho = Ho
        self.Eo = Eo
#         self.initial_state.data[...] = np.random.randn(Ho)
        self.bos_embeding.data[...] = np.random.randn(Eo)

        if init_orth:
            ortho_init(self.gru)
            ortho_init(self.lin_o)
            ortho_init(self.maxo)

    def get_prev_word_embedding(self, inpt):
        if self.pointer_mechanism:
            mb_size = inpt.data.shape[0]
            broadcasted_Vp = F.broadcast_to(self.Vparray, (mb_size,))
            broadcasted_Vm = F.broadcast_to(self.Vmarray, (mb_size,))
            prev_y_v = self.decoder_chain.emb(F.minimum(inpt, broadcasted_Vp))
            prev_y_p = self.decoder_chain.ptr_mec.get_repr_ptr(F.maximum(inpt-broadcasted_Vm, 0))
            prev_y = F.concat((prev_y_v, prev_y_p), axis = 1)
        else:
            prev_y = self.decoder_chain.emb(inpt)
        return prev_y

    def give_conditionalized_cell(self, fb_concat, src_mask, noise_on_prev_word=False,
                                  mode="test", lexicon_probability_matrix=None, lex_epsilon=1e-3, demux=False):
        assert mode in "test train".split()
        mb_size, nb_elems, Hi = fb_concat.data.shape
        assert Hi == self.Hi, "%i != %i" % (Hi, self.Hi)

        compute_ctxt = self.attn_module(fb_concat, src_mask)
#         print "cell mb_size",  mb_size
        if not demux:
            return ConditionalizedDecoderCell(self, compute_ctxt, mb_size, noise_on_prev_word=noise_on_prev_word,
                                              mode=mode, lexicon_probability_matrix=lexicon_probability_matrix, lex_epsilon=lex_epsilon)
        else:
            assert mb_size == 1
            assert demux >= 1
            compute_ctxt = self.attn_module.compute_ctxt_demux(fb_concat, src_mask)
            return ConditionalizedDecoderCell(self, compute_ctxt, None, noise_on_prev_word=noise_on_prev_word,
                                              mode=mode, lexicon_probability_matrix=lexicon_probability_matrix, lex_epsilon=lex_epsilon,
                                              demux=True)

    def compute_loss(self, fb_concat, src_mask, targets, raw_loss_info=False, keep_attn_values=False,
                     noise_on_prev_word=False, use_previous_prediction=0, mode="test", per_sentence=False,
                     lexicon_probability_matrix=None, lex_epsilon=1e-3,
                     use_soft_prediction_feedback=False, 
                    use_gumbel_for_soft_predictions=False,
                    temperature_for_soft_predictions=1.0
                     ):
        decoding_cell = self.give_conditionalized_cell(fb_concat, src_mask, noise_on_prev_word=noise_on_prev_word,
                                                       mode=mode, lexicon_probability_matrix=lexicon_probability_matrix, lex_epsilon=lex_epsilon)
        
        if self.char_enc_emb is not None:
            loss_computer = make_MSE_cross_entropy(self.char_enc_emb)
        else:
            loss_computer = softmax_cross_entropy
        
        loss, attn_list = compute_loss_from_decoder_cell(decoding_cell, targets,
                                                         use_previous_prediction=use_previous_prediction,
                                                         raw_loss_info=raw_loss_info,
                                                         per_sentence=per_sentence,
                                                         keep_attn=keep_attn_values,
                                                        use_soft_prediction_feedback=use_soft_prediction_feedback, 
                                                        use_gumbel_for_soft_predictions=use_gumbel_for_soft_predictions,
                                                        temperature_for_soft_predictions=temperature_for_soft_predictions,
                                                        loss_computer=loss_computer)
        return loss, attn_list

    def sample(self, fb_concat, src_mask, nb_steps, mb_size, lexicon_probability_matrix=None,
               lex_epsilon=1e-3, best=False, keep_attn_values=False, need_score=False):
        decoding_cell = self.give_conditionalized_cell(fb_concat, src_mask, noise_on_prev_word=False,
                                                       mode="test", lexicon_probability_matrix=lexicon_probability_matrix,
                                                       lex_epsilon=lex_epsilon)
        
        if self.char_enc_emb is not None:
            sequences, attn_list = sample_from_decoder_cell_charenc(decoding_cell, nb_steps, keep_attn_values=keep_attn_values)
            score = None
        else:
            sequences, score, attn_list = sample_from_decoder_cell(decoding_cell, nb_steps, best=best,
                                                               keep_attn_values=keep_attn_values,
                                                               need_score=need_score)

        return sequences, score, attn_list

