import numpy as np
import datajoint as dj
import io
import av
from PIL import Image
from tqdm import tqdm
from foundation.utils.logging import logger


stimulus = dj.create_virtual_module("stimulus", "pipeline_stimulus")
schema = dj.schema("foundation_stimuli")


class ConditionMixin:
    @property
    def frames(self):
        """
        Returns
        -------
        List[Image]
            stimulus frames
        """
        raise NotImplementedError


@schema
class Clip(dj.Computed, ConditionMixin):
    definition = """
    -> stimulus.Clip
    ---
    frames      : int unsigned  # number of stimulus frames
    """

    @staticmethod
    def decode(condition_hash):
        key = dict(condition_hash=condition_hash)

        clip = stimulus.Movie * stimulus.Movie.Clip * stimulus.Clip & key
        clip, start, end, fps = clip.fetch1("clip", "skip_time", "cut_after", "frame_rate")

        start, end = map(float, [start, end])
        start = round(start * fps)
        end = start + round(end * fps)

        reader = av.open(io.BytesIO(clip.tobytes()), mode="r")
        for i, frame in enumerate(reader.decode()):

            if i < start:
                continue
            if i == end:
                return

            yield frame.to_image().convert(mode="L")

    def make(self, key):
        frames = 0
        for _ in self.decode(**key):
            frames += 1

        key = dict(key, frames=frames)
        self.insert1(key)

    @property
    def frames(self):
        condition_hash = self.fetch1("condition_hash")
        return list(self.decode(condition_hash))
