import random

import skimage
from skimage import exposure
from io import BytesIO
from PIL import Image, ImageOps, ImageEnhance
import PIL

from torchvision.transforms import Scale

class RandomScale(Scale):
    def __init__(self, prob, scales):
        self.prob = prob
        self.scales = scales

    def __call__(self, img):
        for scale in self.scales:
            if random.random() < self.prob:
                w,h = img.size
                return Scale(size=(int(w * scale), int(h * scale)))(img)

        return img

    def __repr__(self):
        return self.__class__.__name__ + '()'


class RandomCompression(object):
    def __init__(self, prob, rates):
        self.prob = prob
        self.rates = rates

    def __call__(self, img):
        for rate in self.rates:
            if random.random() < self.prob:
                buffer = BytesIO()
                img.save(buffer, "JPEG", quality=rate)
                buffer.seek(0)
                byteImg = buffer.read()

                # Non test code
                dataBytesIO = BytesIO(byteImg)
                return Image.open(dataBytesIO)

        return img

def do_gamma(im, gamma):
    """Fast gamma correction with PIL's image.point() method"""
    invert_gamma = 1.0/gamma
    lut = [pow(x/255., invert_gamma) * 255 for x in range(256)]
    lut = lut*3 # need one set of data for each band for RGB
    im = im.point(lut)
    return im


class RandomGamma(object):
    def __init__(self, prob, gammas):
        self.prob = prob
        self.gammas = gammas


    def __call__(self, img):
        for gamma in self.gammas:
            if random.random() < self.prob:
                new_img =  do_gamma(img, gamma)
                return new_img

        return img
