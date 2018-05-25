import argparse
import mxnet as mx

from gluoncv import data as gdata
from gluoncv.utils.metrics.voc_detection import VOC07MApMetric
from tqdm import tqdm

from data.bbox import decode_detect
from data.transform import RCNNDefaultValTransform, generate_batch
from net.model import get_net
from net.symbol_resnet import get_resnet_test


IMG_SHORT_SIDE = 600
IMG_LONG_SIDE = 1000
IMG_PIXEL_MEANS = (0.0, 0.0, 0.0)
IMG_PIXEL_STDS = (1.0, 1.0, 1.0)

RPN_ANCHORS = 9
RPN_ANCHOR_SCALES = (8, 16, 32)
RPN_ANCHOR_RATIOS = (0.5, 1, 2)
RPN_FEAT_STRIDE = 16
RPN_PRE_NMS_TOP_N = 6000
RPN_POST_NMS_TOP_N = 300
RPN_NMS_THRESH = 0.7
RPN_MIN_SIZE = 16

RCNN_CLASSES = 21
RCNN_FEAT_STRIDE = 16
RCNN_POOLED_SIZE = (14, 14)
RCNN_BATCH_SIZE = 1
RCNN_BBOX_STDS = (0.1, 0.1, 0.2, 0.2)
RCNN_CONF_THRESH = 1e-3
RCNN_NMS_THRESH = 0.3


def parse_args():
    parser = argparse.ArgumentParser(description='Test a Fast R-CNN network')
    # testing
    parser.add_argument('prefix', help='model to test with', type=str)
    parser.add_argument('epoch', help='model to test with', type=int)
    parser.add_argument('gpu', help='GPU device to test with', type=int)
    args = parser.parse_args()
    return args


def main():
    # print config
    args = parse_args()
    print('Called with argument: %s' % args)
    ctx = mx.gpu(args.gpu)

    # load testing data
    val_dataset = gdata.VOCDetection(splits=[(2007, 'test')])
    val_transform = RCNNDefaultValTransform(short=IMG_SHORT_SIDE, max_size=IMG_LONG_SIDE,
                                            mean=IMG_PIXEL_MEANS, std=IMG_PIXEL_STDS)
    val_loader = gdata.DetectionDataLoader(val_dataset.transform(val_transform),
                                           batch_size=1, shuffle=False, last_batch="keep", num_workers=4)

    # load model
    sym = get_resnet_test(
        num_anchors=RPN_ANCHORS, anchor_scales=RPN_ANCHOR_SCALES, anchor_ratios=RPN_ANCHOR_RATIOS,
        rpn_feature_stride=RPN_FEAT_STRIDE, rpn_pre_topk=RPN_PRE_NMS_TOP_N, rpn_post_topk=RPN_POST_NMS_TOP_N,
        rpn_nms_thresh=RPN_NMS_THRESH, rpn_min_size=RPN_POST_NMS_TOP_N,
        num_classes=RCNN_CLASSES, rcnn_feature_stride=RCNN_FEAT_STRIDE,
        rcnn_pooled_size=RCNN_POOLED_SIZE, rcnn_batch_size=RCNN_BATCH_SIZE)
    predictor = get_net(sym, args.prefix, args.epoch, ctx, short=IMG_SHORT_SIDE, max_size=IMG_LONG_SIDE)

    # start detection
    metric = VOC07MApMetric(iou_thresh=0.5, class_names=val_dataset.classes)
    with tqdm(total=len(val_dataset)) as pbar:
        for ib, batch in enumerate(val_loader):
            im_tensor, im_info, label = batch
            data_batch = generate_batch(im_tensor, im_info)

            gt_ids = label.slice_axis(axis=-1, begin=4, end=5)
            gt_bboxes = label.slice_axis(axis=-1, begin=0, end=4)
            gt_difficults = label.slice_axis(axis=-1, begin=5, end=6) if label.shape[-1] > 5 else None

            # forward
            im_info = im_info[0]
            output = predictor.predict(data_batch)
            rois = output['rois_output'][:, 1:]
            scores = output['cls_prob_reshape_output'][0]
            bbox_deltas = output['bbox_pred_reshape_output'][0]

            # post processing
            det = decode_detect(rois, scores, bbox_deltas, im_info,
                                bbox_stds=RCNN_BBOX_STDS, nms_thresh=RCNN_NMS_THRESH)
            cls = det.slice_axis(axis=-1, begin=0, end=1)
            conf = det.slice_axis(axis=-1, begin=1, end=2)
            boxes = det.slice_axis(axis=-1, begin=2, end=6)
            cls -= 1

            metric.update(boxes.expand_dims(0), cls.expand_dims(0), conf.expand_dims(0),
                          gt_bboxes, gt_ids, gt_difficults)
            pbar.update(batch[0].shape[0])
    names, values = metric.get()

    # print
    for k, v in zip(names, values):
        print(k, v)


if __name__ == '__main__':
    main()
