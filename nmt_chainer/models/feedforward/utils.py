import chainer
import numpy as np
import chainer.functions as F
import chainer.links as L
from chainer import Variable, Chain, ChainList

########################################################################
# Feed Forward layer with pass-through and normalization
#

class FeedForward(Chain):
    def __init__(self, d_model=512, d_ff=2048, dropout=None):
        super(FeedForward, self).__init__(
            lin1 = L.Linear(d_model, d_ff),
            lin2 = L.Linear(d_ff, d_model),
            normalization_layer = L.LayerNormalization()
        )
        
        self.dropout = dropout
        
    def __call__(self, x_input, train=True):
#         print "FF", x_input.data
        if len(x_input.data.shape) > 2:
            x = F.reshape(x_input, (-1, x_input.shape[-1]))
        else:
            x = x_input
            
        ff_output = self.lin2(F.relu(self.lin1(x)))
        
        if self.dropout is not None:
            ff_output = F.dropout(ff_output, self.dropout, train=train)
            
        norm_ff_output = self.normalization_layer(ff_output + x)
        
        if len(x_input.data.shape) > 2:
            norm_ff_output = F.reshape(norm_ff_output, x_input.data.shape)
            
#         print "FFR", norm_ff_output.data
        return norm_ff_output

#########################################################################
# Reshaping utility function
#

def apply_linear_layer_to_last_dims(Q, w_Q):
    mb_size_Q, n_Q, d_model_Q = Q.data.shape
    return F.reshape(w_Q(F.reshape(Q, (mb_size_Q * n_Q, d_model_Q))), (mb_size_Q, n_Q, -1))


########################################################################
# Generating position vectors according to Google's paper formula
#

def generate_pos_vectors(d_model, max_length):
    pos_component = np.arange(max_length, dtype = np.float32)
    dim_component = np.arange(d_model, dtype = np.float32)
    dim_component_even = np.floor_divide(dim_component, 2) * 2
    dim_factor = np.power(1e-4, dim_component_even / d_model)
    pos_dim = pos_component[:, None] * dim_factor[None, :]
    pos_dim[:, ::2] = np.sin(pos_dim[:, ::2])
    pos_dim[:, 1::2] = np.cos(pos_dim[:, 1::2])
    return pos_dim
    
########################################################################
# batch handling
#

def make_batch_mask(mb_size, n_head, max_length_1, max_length_2, 
                    key_seq_lengths=None,
                    future_mask=False,
                    mask_value=-10000):
    
    if future_mask:
        assert max_length_1 == max_length_2
        mask = np.array(
                np.broadcast_to(( (-mask_value) * (np.tri(max_length_1, dtype = np.float32)-1))[None,None,:,:], 
                                (mb_size, n_head, max_length_1, max_length_2))
                )
    else:
        mask = np.zeros((mb_size, n_head, max_length_1, max_length_2), dtype = np.float32)
        
    if key_seq_lengths is not None:
        assert mb_size == len(key_seq_lengths)
        assert min(key_seq_lengths) > 0
        assert max(key_seq_lengths) <= max_length_2
        for num_batch, length in enumerate(key_seq_lengths):
            mask[num_batch, :, :, length:] = mask_value

    return mask

def pad_data(data, pad_value=0, add_eos=None):
    mb_size = len(data)
    padded_length = max(len(x) for x in data)
    if add_eos is not None:
        padded_length += 1
    padded_array = np.zeros((mb_size, padded_length), dtype=np.int32)
    if pad_value != 0:
        padded_array += pad_value
    for num_batch, seq in enumerate(data):
        padded_array[num_batch, :len(seq)] = seq
        if add_eos is not None:
            padded_array[num_batch, len(seq)] = add_eos
    return padded_array

def cut_minibatch(minibatch, new_mb_size):
    current_mb_size = minibatch.data.shape[0]
    assert new_mb_size <= current_mb_size
    if current_mb_size == new_mb_size:
        return minibatch
    new_minibatch, _ = F.split_axis(minibatch, (new_mb_size,), axis=0, force_tuple=True)
    return new_minibatch

    