import visdom
import numpy as np

vis = visdom.Visdom()
vis.text('Visualizing segmentation output')

def show(pred, labels):
    print(pred.shape, labels.shape)
    vis.images(np.hstack([pred[0], labels[0]]))
