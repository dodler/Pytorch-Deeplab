import argparse

import torch.nn.functional as F
import torch
import torch.nn as nn
from torch.utils import data
import numpy as np
import pickle
import cv2
from torch.autograd import Variable
import torch.optim as optim
import scipy.misc
import torch.backends.cudnn as cudnn
import sys
import os
import os.path as osp
from deeplab.model import Res_Deeplab
from deeplab.loss import CrossEntropy2d
from deeplab.datasets import VOCDataSet
from deeplab.datasets import GenericDataset

import torchvision.transforms as transforms
from torchvision.transforms import *
import torch.nn.functional as F

import vis

from random_transforms import *

tsize=321

rgb_mean = (0.4914, 0.4822, 0.4465)
rgb_std = (0.2023, 0.1994, 0.2010)
# todo add augmentation

common_transforms = Compose([
                             transforms.RandomRotation(30)
                             ])

train_transform = Compose([
                           RandomGamma(0.4, [0.8, 1.2]),
                           RandomScale(0.4, [0.5, 0.8, 1.5, 2.0]),
                           RandomCompression(0.4, [70, 90]),
                           Resize((tsize, tsize)),
                           ToTensor(),
                           Normalize(rgb_mean, rgb_std)
                           ])

mask_transform = Compose([Resize((tsize,tsize)),ToTensor()])

val_transform = transforms.Compose([Resize((tsize,tsize)), ToTensor(), Normalize(rgb_mean, rgb_std)])

#import matplotlib.pyplot as plt
import random
import timeit
start = timeit.default_timer()

IMG_MEAN = np.array((104.00698793,116.66876762,122.67891434), dtype=np.float32)

BATCH_SIZE = 8
DATA_DIRECTORY = '/home/dhc/nevus_masks/'
DATA_LIST_PATH = './dataset/list/train_aug.txt'
IGNORE_LABEL = 255
INPUT_SIZE = '321,321'
LEARNING_RATE = 2.5e-5
MOMENTUM = 0.9
NUM_CLASSES = 2
NUM_STEPS = 20000
POWER = 0.9
RANDOM_SEED = 1234
RESTORE_FROM = './dataset/MS_DeepLab_resnet_pretrained_COCO_init.pth'
SAVE_NUM_IMAGES = 2
SAVE_PRED_EVERY = 1000
SNAPSHOT_DIR = './snapshots/'
WEIGHT_DECAY = 0.00005

def get_arguments():
    """Parse all the arguments provided from the CLI.
    
    Returns:
      A list of parsed arguments.
    """
    parser = argparse.ArgumentParser(description="DeepLab-ResNet Network")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help="Number of images sent to the network in one step.")
    parser.add_argument("--data-dir", type=str, default=DATA_DIRECTORY,
                        help="Path to the directory containing the PASCAL VOC dataset.")
    parser.add_argument("--data-list", type=str, default=DATA_LIST_PATH,
                        help="Path to the file listing the images in the dataset.")
    parser.add_argument("--ignore-label", type=int, default=IGNORE_LABEL,
                        help="The index of the label to ignore during the training.")
    parser.add_argument("--input-size", type=str, default=INPUT_SIZE,
                        help="Comma-separated string with height and width of images.")
    parser.add_argument("--is-training", action="store_true",
                        help="Whether to updates the running means and variances during the training.")
    parser.add_argument("--learning-rate", type=float, default=LEARNING_RATE,
                        help="Base learning rate for training with polynomial decay.")
    parser.add_argument("--momentum", type=float, default=MOMENTUM,
                        help="Momentum component of the optimiser.")
    parser.add_argument("--not-restore-last", action="store_true",
                        help="Whether to not restore last (FC) layers.")
    parser.add_argument("--num-classes", type=int, default=NUM_CLASSES,
                        help="Number of classes to predict (including background).")
    parser.add_argument("--num-steps", type=int, default=NUM_STEPS,
                        help="Number of training steps.")
    parser.add_argument("--power", type=float, default=POWER,
                        help="Decay parameter to compute the learning rate.")
    parser.add_argument("--random-mirror", action="store_true",
                        help="Whether to randomly mirror the inputs during the training.")
    parser.add_argument("--random-scale", action="store_true",
                        help="Whether to randomly scale the inputs during the training.")
    parser.add_argument("--random-seed", type=int, default=RANDOM_SEED,
                        help="Random seed to have reproducible results.")
    parser.add_argument("--restore-from", type=str, default=RESTORE_FROM,
                        help="Where restore model parameters from.")
    parser.add_argument("--save-num-images", type=int, default=SAVE_NUM_IMAGES,
                        help="How many images to save.")
    parser.add_argument("--save-pred-every", type=int, default=SAVE_PRED_EVERY,
                        help="Save summaries and checkpoint every often.")
    parser.add_argument("--snapshot-dir", type=str, default=SNAPSHOT_DIR,
                        help="Where to save snapshots of the model.")
    parser.add_argument("--weight-decay", type=float, default=WEIGHT_DECAY,
                        help="Regularisation parameter for L2-loss.")
    parser.add_argument("--gpu", type=int, default=0,
                        help="choose gpu device.")
    return parser.parse_args()

args = get_arguments()

#def loss_calc(pred, label, gpu):
def loss_calc(pred, label):
    """
    This function returns cross entropy loss for semantic segmentation
    """
    #print(str(pred), str(label))
    # out shape batch_size x channels x h x w -> batch_size x channels x h x w
    # label shape h x w x 1 x batch_size  -> batch_size x 1 x h x w
#    label = Variable(label.long()).cuda(gpu)
    label = Variable(label.long()).cuda()
    #criterion = torch.nn.BCELoss().cuda(gpu)
    criterion = CrossEntropy2d().cuda()
    #criterion = nn.CrossEntropyLoss().cuda(gpu)
    
    #return cross_entropy2d(pred.view(8,1,321,321), label.view(8,1,321,321))
    return criterion(pred, label)


def lr_poly(base_lr, iter, max_iter, power):
    return base_lr*((1-float(iter)/max_iter)**(power))


def get_1x_lr_params_NOscale(model):
    """
    This generator returns all the parameters of the net except for 
    the last classification layer. Note that for each batchnorm layer, 
    requires_grad is set to False in deeplab_resnet.py, therefore this function does not return 
    any batchnorm parameter
    """
    b = []

    b.append(model.conv1)
    b.append(model.bn1)
    b.append(model.layer1)
    b.append(model.layer2)
    b.append(model.layer3)
    b.append(model.layer4)

    
    for i in range(len(b)):
        for j in b[i].modules():
            jj = 0
            for k in j.parameters():
                jj+=1
                if k.requires_grad:
                    yield k

def get_10x_lr_params(model):
    """
    This generator returns all the parameters for the last layer of the net,
    which does the classification of pixel into classes
    """
    b = []
    b.append(model.layer5.parameters())

    for j in range(len(b)):
        for i in b[j]:
            yield i

def adjust_learning_rate(optimizer, epoch):
    """Sets the learning rate to the initial LR decayed by 10 every 30 epochs"""
    lr = args.learning_rate * (0.1 ** (epoch // 30))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr

epochs = 200

def main():
    """Create the model and start the training."""
    
    h, w = map(int, args.input_size.split(','))
    input_size = (h, w)

    print(input_size)

    cudnn.enabled = True
    gpu = args.gpu

    # Create network.
    model = Res_Deeplab(num_classes=args.num_classes)
    # For a small batch size, it is better to keep 
    # the statistics of the BN layers (running means and variances)
    # frozen, and to not update the values provided by the pre-trained model. 
    # If is_training=True, the statistics will be updated during the training.
    # Note that is_training=False still updates BN parameters gamma (scale) and beta (offset)
    # if they are presented in var_list of the optimiser definition.

    '''
#    saved_state_dict = torch.load(args.restore_from)
#    new_params = model.state_dict().copy()
#    for i in saved_state_dict:
        #Scale.layer5.conv2d_list.3.weight
#        i_parts = i.split('.')
        # print i_parts
#        if not args.num_classes == 21 or not i_parts[1]=='layer5':
#            new_params['.'.join(i_parts[1:])] = saved_state_dict[i]
#    model.load_state_dict(new_params)
    '''
    #model.float()
    #model.eval() # use_global_stats = True
#    model = nn.DataParallel(model)
    model.train()
    model.cuda()
#    model.cuda(args.gpu)
    
    cudnn.benchmark = True

    if not os.path.exists(args.snapshot_dir):
        os.makedirs(args.snapshot_dir)


#    trainloader = data.DataLoader(VOCDataSet(args.data_dir, args.data_list, max_iters=args.num_steps*args.batch_size, crop_size=input_size, 
#                    scale=args.random_scale, mirror=args.random_mirror, mean=IMG_MEAN), 
#                    batch_size=args.batch_size, shuffle=True, num_workers=5, pin_memory=True)

    dataset = GenericDataset(DATA_DIRECTORY,'train', train_transform, mask_transform)
    trainloader = data.DataLoader(dataset, batch_size = BATCH_SIZE, shuffle=True, num_workers = 4, pin_memory=True)

#    optimizer = optim.SGD([{'params': get_1x_lr_params_NOscale(model), 'lr': args.learning_rate }, 
#                 {'params': get_10x_lr_params(model), 'lr': 10*args.learning_rate}], 
#                lr=args.learning_rate, momentum=args.momentum,weight_decay=args.weight_decay)
    optimizer = optim.Adam(filter(lambda p:p.requires_grad,model.parameters()), 1e-4)
#    optimizer = optim.Adam([{'params': get_1x_lr_params_NOscale(model), 'lr': args.learning_rate }], 1e-4)
#    optimizer = optim.Adam(get_1x_lr_params_NOscale(model), 1e-4)
#    optimizer = optim.Adam(get_10x_lr_params(model), lr=1e-5)
    optimizer.zero_grad()

    interp = nn.Upsample(size=input_size, mode='bilinear')

    for e in range(epochs):
        for i_iter, batch in enumerate(trainloader):
            images, labels, _, _ = batch
#        images = Variable(images).cuda(args.gpu)
            images = Variable(images).cuda()

            optimizer.zero_grad()
            adjust_learning_rate(optimizer, i_iter)
            pred = interp(model(images))

            if i_iter % 50 == 0:
                vis.show(F.sigmoid(pred)[:,1].cpu().data.round().numpy()[0:],labels.numpy())

                loss = loss_calc(pred, labels.squeeze())
#        loss = loss_calc(pred, labels.squeeze(), args.gpu)
                loss.backward()
                optimizer.step()

                print('iter = ', i_iter, 'of', args.num_steps,'completed, loss = ', loss.data.cpu().numpy())

 #       if i_iter >= args.num_steps-1:
     #           print('save model ...')
 #           torch.save(model.state_dict(),osp.join(args.snapshot_dir, 'VOC12_scenes_'+str(args.num_steps)+'.pth'))
#            break

                if i_iter % 200 == 0 and i_iter!=0:
                    print('taking snapshot ...')
                    torch.save(model.state_dict(),osp.join(args.snapshot_dir, 'VOC12_scenes_'+str(i_iter)+'.pth'))     

    end = timeit.default_timer()
    print(end-start,'seconds')

if __name__ == '__main__':
    main()
