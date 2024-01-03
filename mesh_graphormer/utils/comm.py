"""
Copyright (c) Microsoft Corporation.
Licensed under the MIT license.

This file contains primitives for multi-gpu communication.
This is useful when doing distributed training.
"""

import pickle
import torch
import torch.distributed as dist


def get_world_size():
    if not dist.is_available():
        return 1
    if not dist.is_initialized():
        return 1
    return dist.get_world_size()


def get_rank():
    if not dist.is_available():
        return 0
    if not dist.is_initialized():
        return 0
    return dist.get_rank()


def is_main_process():
    return get_rank() == 0


def synchronize():
    """
    Helper function to synchronize (barrier) among all processes when
    using distributed training
    """
    if not dist.is_available():
        return
    if not dist.is_initialized():
        return
    world_size = dist.get_world_size()
    if world_size == 1:
        return
    dist.barrier()


def gather_on_master(data):
    """Same as all_gather, but gathers data on master process only, using CPU.
    Thus, this does not work with NCCL backend unless they add CPU support.

    The memory consumption of this function is ~ 3x of data size. While in
    principal, it should be ~2x, it's not easy to force Python to release
    memory immediately and thus, peak memory usage could be up to 3x.
    """
    world_size = get_world_size()
    if world_size == 1:
        return [data]

    # serialized to a Tensor
    buffer = pickle.dumps(data)
    # trying to optimize memory, but in fact, it's not guaranteed to be released
    del data
    storage = torch.ByteStorage.from_buffer(buffer)
    del buffer
    tensor = torch.ByteTensor(storage)

    # obtain Tensor size of each rank
    local_size = torch.LongTensor([tensor.numel()])
    size_list = [torch.LongTensor([0]) for _ in range(world_size)]
    dist.all_gather(size_list, local_size)
    size_list = [int(size.item()) for size in size_list]
    max_size = max(size_list)

    if local_size != max_size:
        padding = torch.ByteTensor(size=(max_size - local_size,))
        tensor = torch.cat((tensor, padding), dim=0)
        del padding

    if is_main_process():
        tensor_list = []
        for _ in size_list:
            tensor_list.append(torch.ByteTensor(size=(max_size,)))
        dist.gather(tensor, gather_list=tensor_list, dst=0)
        del tensor
    else:
        dist.gather(tensor, gather_list=[], dst=0)
        del tensor
        return

    data_list = []
    for tensor in tensor_list:
        buffer = tensor.cpu().numpy().tobytes()
        del tensor
        data_list.append(pickle.loads(buffer))
        del buffer

    return data_list


def reduce_dict(input_dict, average=True):
    """
    Args:
        input_dict (dict): all the values will be reduced
        average (bool): whether to do average or sum
    Reduce the values in the dictionary from all processes so that process with rank
    0 has the averaged results. Returns a dict with the same fields as
    input_dict, after reduction.
    """
    world_size = get_world_size()
    if world_size < 2:
        return input_dict
    with torch.no_grad():
        names = []
        values = []
        # sort the keys so that they are consistent across processes
        for k in sorted(input_dict.keys()):
            names.append(k)
            values.append(input_dict[k])
        values = torch.stack(values, dim=0)
        dist.reduce(values, dst=0)
        if dist.get_rank() == 0 and average:
            # only main process gets accumulated, so only divide by
            # world_size in this case
            values /= world_size
        reduced_dict = {k: v for k, v in zip(names, values)}
    return reduced_dict
