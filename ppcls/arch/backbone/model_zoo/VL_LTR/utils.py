import math
import warnings

import paddle
from paddle import nn
from paddle.nn import functional as F
from paddle.nn.functional import interpolate
from paddle.autograd import PyLayer
import paddle.distributed as dist
class GatherLayer(PyLayer):
    '''
        Gather tensors from all process, support backward propagation.
    '''

    @staticmethod
    def forward(ctx, input):
        ctx.save_for_backward(input)
        output = [paddle.zeros_like(input) for _ in range(dist.get_world_size())]
        dist.all_gather(output, input)
        return tuple(output)
    
    @staticmethod
    def backward(ctx, *grads):
        input, = ctx.saved_tensors
        grad_out = paddle.zeros_like(input)
        grad_out[:] = grads[dist.get_rank()] * dist.get_world_size()
        return grad_out
    
def interpolate_pos_embed(pos_embed_checkpoint: paddle.Tensor, new_patch_size, num_extra_tokens=1):
    # interpolate position embedding
    embedding_size = pos_embed_checkpoint.shape[1]
    # height (== width) for the checkpoint position embedding
    orig_size = int((pos_embed_checkpoint.shape[0] - num_extra_tokens) ** 0.5)
    # height (== width) for the new position embedding
    # class_token and dist_token are kept unchanged
    extra_tokens = pos_embed_checkpoint[:num_extra_tokens, :]
    # only the position tokens are interpolated
    pos_tokens = pos_embed_checkpoint[num_extra_tokens:, :]
    pos_tokens = paddle.transpose(paddle.reshape(pos_tokens,(orig_size, orig_size, embedding_size)),(0, 3, 1, 2))
    pos_tokens = interpolate(pos_tokens, size=(new_patch_size, new_patch_size), mode='bicubic', align_corners=False)

    pos_tokens = paddle.transpose(pos_tokens,(0, 2, 3, 1))
    pos_tokens = paddle.flatten(pos_tokens,(1,2))
    pos_tokens = paddle.squeeze(pos_tokens,axis=0)

    new_pos_embed = paddle.concat((extra_tokens, pos_tokens), axis=0)
    return new_pos_embed


def _no_grad_trunc_normal_(tensor, mean, std, a, b):
    # Cut & paste from PyTorch official master until it's in a few official releases - RW
    # Method based on https://people.sc.fsu.edu/~jburkardt/presentations/truncated_normal.pdf
    def norm_cdf(x):
        # Computes standard normal cumulative distribution function
        return (1. + math.erf(x / math.sqrt(2.))) / 2.

    if (mean < a - 2 * std) or (mean > b + 2 * std):
        warnings.warn("mean is more than 2 std from [a, b] in nn.init.trunc_normal_. "
                      "The distribution of values may be incorrect.",
                      stacklevel=2)

    with paddle.no_grad():
        # Values are generated by using a truncated uniform distribution and
        # then using the inverse CDF for the normal distribution.
        # Get upper and lower cdf values
        l = norm_cdf((a - mean) / std)
        u = norm_cdf((b - mean) / std)

        # Uniformly fill tensor with values from [l, u], then translate to
        # [2l-1, 2u-1].
        tensor = paddle.uniform((2 * l - 1, 2 * u - 1))

        # Use inverse cdf transform for normal distribution to get truncated
        # standard normal
        tensor = paddle.erfinv(tensor)

        # Transform to proper mean, std
        tensor = paddle.multiply(tensor,std * math.sqrt(2.))
        tensor = paddle.add(tensor,mean)

        # Clamp to ensure it's in the proper range
        tensor = paddle.clip(tensor,min=a,max=b)
        return tensor


def trunc_normal_(tensor, mean=0., std=1., a=-2., b=2.):
    # type: (Tensor, float, float, float, float) -> Tensor
    r"""Fills the input Tensor with values drawn from a truncated
    normal distribution. The values are effectively drawn from the
    normal distribution :math:`\mathcal{N}(\text{mean}, \text{std}^2)`
    with values outside :math:`[a, b]` redrawn until they are within
    the bounds. The method used for generating the random values works
    best when :math:`a \leq \text{mean} \leq b`.
    Args:
        tensor: an n-dimensional `torch.Tensor`
        mean: the mean of the normal distribution
        std: the standard deviation of the normal distribution
        a: the minimum cutoff value
        b: the maximum cutoff value
    Examples:
        >>> w = torch.empty(3, 5)
        >>> nn.init.trunc_normal_(w)
    """
    return _no_grad_trunc_normal_(tensor, mean, std, a, b)