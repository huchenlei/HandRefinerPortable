import numpy as np
from PIL import Image
from .util import resize_image_with_pad, common_input_validate, HWC3, custom_hf_download
from hand_refiner.pipeline import MeshGraphormerMediapipe, args

class MeshGraphormerDetector:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    @classmethod
    def from_pretrained(cls, pretrained_model_or_path, filename=None, hrnet_filename=None, cache_dir=None, device=None):
        filename = filename or "graphormer_hand_state_dict.bin"
        hrnet_filename = hrnet_filename or "hrnetv2_w64_imagenet_pretrained.pth"
        args.resume_checkpoint = custom_hf_download(pretrained_model_or_path, filename, cache_dir)
        args.hrnet_checkpoint = custom_hf_download(pretrained_model_or_path, hrnet_filename, cache_dir)
        args.device = device
        pipeline = MeshGraphormerMediapipe(args)
        return cls(pipeline)
    
    def to(self, device):
        self.pipeline._model.to(device)
        self.pipeline.mano_model.to(device)
        self.pipeline.mano_model.layer.to(device)
        return self
    
    def __call__(self, input_image=None, mask_bbox_padding=30, detect_resolution=512, output_type=None, upscale_method="INTER_CUBIC", **kwargs):
        input_image, output_type = common_input_validate(input_image, output_type, **kwargs)

        depth_map, mask, info = self.pipeline.get_depth(input_image, mask_bbox_padding)
        if depth_map is None:
            depth_map = np.zeros_like(input_image)
            mask = np.zeros_like(input_image)

        #The hand is small
        depth_map, mask = HWC3(depth_map), HWC3(mask)
        depth_map, remove_pad = resize_image_with_pad(depth_map, detect_resolution, upscale_method)
        depth_map = remove_pad(depth_map)
        if output_type == "pil":
            depth_map = Image.fromarray(depth_map)
            mask = Image.fromarray(mask)
            
        return depth_map, mask, info
