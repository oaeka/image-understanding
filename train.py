import torch.optim as optim
import yaml
from torch.utils.data import DataLoader

from Models import Transformer, ScheduledOptimizer
from data import dataset
import torch
import os
from tqdm import tqdm
import time
import math
from torch.nn import NLLLoss
import torch.nn.functional as F


# def calc_loss(real, pred):
#     mask = tf.math.logical_not(tf.math.equal(real, 0))
#     loss_ = loss_object(real, pred)
#
#     mask = tf.cast(mask, dtype=loss_.dtype)
#     loss_ *= mask
#     return tf.reduce_sum(loss_) / tf.reduce_sum(mask)

def cal_loss(pred, gold, trg_pad_idx, smoothing=False):
    ''' Calculate cross entropy loss, apply label smoothing if needed. '''

    if smoothing:
        gold = gold.contiguous().view(-1)
        eps = 0.1
        n_class = pred.size(1)

        one_hot = torch.zeros_like(pred).scatter(1, gold.view(-1, 1), 1)
        one_hot = one_hot * (1 - eps) + (1 - one_hot) * eps / (n_class - 1)
        log_prb = F.log_softmax(pred, dim=1)

        non_pad_mask = gold.ne(trg_pad_idx)
        loss = -(one_hot * log_prb).sum(dim=1)
        loss = loss.masked_select(non_pad_mask).sum()  # average later
    else:
        loss = F.cross_entropy(pred, gold, ignore_index=trg_pad_idx, reduction='mean')
    return loss


def train_epoch(model, training_data, optimizer, device):
    """ Epoch operation in training phase"""
    model.train()
    total_loss, train_accuracy = 0, 0

    desc = '  - (Training)   '
    tq = tqdm(training_data, mininterval=2, desc=desc, leave=False)
    for img_tensor, target, img_name in tq:
        # prepare data
        src_seq = img_tensor.to(device)
        target_inp = target[:, :-1].contiguous().to(device)
        target_real = target[:, 1:].contiguous().to(device)

        # forward prop
        optimizer.zero_grad()

        pred = model(src_seq, target_inp)
        loss = cal_loss(pred.permute((0, 2, 1)), target_real, 0)
        loss.backward()
        optimizer.step_and_update_lr()

        tq.set_description(f'Loss {loss.item()}')
        total_loss += loss.item()
        break

    return total_loss, train_accuracy
    # backward and update parameters
    #     loss, n_correct, n_word = cal_performance(
    #         pred, gold, opt.trg_pad_idx, smoothing=smoothing)
    #     loss.backward()
    #     optimizer.step_and_update_lr()
    #
    #     # note keeping
    #     n_word_total += n_word
    #     n_word_correct += n_correct
    #     total_loss += loss.item()
    #
    # loss_per_word = total_loss / n_word_total
    # accuracy = n_word_correct / n_word_total
    # return loss_per_word, accuracy


def eval_epoch(model, validation_data, device, opt):
    """ Epoch operation in evaluation phase """

    model.eval()
    total_loss, val_accuracy = 0, 0

    desc = '  - (Validation) '
    with torch.no_grad():
        for img_tensor, target, img_name in tqdm(validation_data, mininterval=2, desc=desc, leave=False):
            src_seq = img_tensor.to(device)
            target_inp = target[:, :-1].contiguous().to(device)
            target_real = target[:, 1:].contiguous().to(device)

            pred = model(src_seq, target_inp)
            loss = cal_loss(pred.permute((0, 2, 1)), target_real, 0)
            loss.backward()

            total_loss += loss.item()

    return total_loss, val_accuracy


def train(model, train_data, val_data, optimizer, device, cfg, data):
    if cfg["TENSOR_BOARD"]:
        print("[+] Using Tensorboard")
        from torch.utils.tensorboard import SummaryWriter
        tb_writer = SummaryWriter(log_dir=os.path.join('.', 'tensorboard'))

    log_train_file = os.path.join(cfg["LOGS_DIR"], 'train.log')
    log_valid_file = os.path.join(cfg["LOGS_DIR"], 'valid.log')

    print(f'[+] Training performance will be written to file: {log_train_file} and {log_valid_file}')

    with open(log_train_file, 'w') as log_tf, open(log_valid_file, 'w') as log_vf:
        log_tf.write('epoch,loss,ppl,accuracy\n')
        log_vf.write('epoch,loss,ppl,accuracy\n')

    def print_performances(header, ppl, accu, start_time, lr):
        elapse = (time.time() - start_time) / 60
        print(f"""  - {header:12} ppl: {ppl: 8.5f}, accuracy: {accu:3.3f},
             lr: {lr:8.5f}, elapse: {elapse:3.3f} min, lr{lr}""")

    valid_losses = []
    for epoch_i in range(cfg["EPOCHS"]):
        print(f'[ Epoch {epoch_i}]')

        start = time.time()
        train_loss, train_accu = train_epoch(model, train_data, optimizer, device)
        train_ppl = math.exp(min(train_loss, 100))

        # Current learning loss
        lr = optimizer._optimizer.param_groups[0]['lr']
        print_performances('Training', train_ppl, train_accu, start, lr)

        # Evaluating model
        # start = time.time()
        # valid_loss, valid_accu = eval_epoch(model, val_data, device, cfg)
        # valid_ppl = math.exp(min(valid_loss, 100))
        # print_performances('Validation', valid_ppl, valid_accu, start, lr)
        #
        # valid_losses += [valid_loss]

        # checkpoint = {'epoch': epoch_i, 'settings': cfg, 'model': model.state_dict()}

        # if cfg["SAVE_MODE"] == 'all':
        #     model_name = 'model_accu_{accu:3.3f}.chkpt'.format(accu=100 * valid_accu)
        #     torch.save(checkpoint, model_name)
        # elif cfg["SAVE_MODE"] == 'best':
        #     model_name = 'model.chkpt'
        #     if valid_loss <= min(valid_losses):
        #         torch.save(checkpoint, os.path.join(cfg["SAVE_DIR"], model_name))
        #         print('    - [Info] The checkpoint file has been updated.')
        #
        # with open(log_train_file, 'a') as log_tf, open(log_valid_file, 'a') as log_vf:
        #     log_tf.write('{epoch},{loss: 8.5f},{ppl: 8.5f},{accu:3.3f}\n'.format(
        #         epoch=epoch_i, loss=train_loss,
        #         ppl=train_ppl, accu=100 * train_accu))
        #     log_vf.write('{epoch},{loss: 8.5f},{ppl: 8.5f},{accu:3.3f}\n'.format(
        #         epoch=epoch_i, loss=valid_loss,
        #         ppl=valid_ppl, accu=100 * valid_accu))
        #
        # if cfg["TENSOR_BOARD"]:
        #     tb_writer.add_scalars('ppl', {'train': train_ppl, 'val': valid_ppl}, epoch_i)
        #     tb_writer.add_scalars('accuracy', {'train': train_accu * 100, 'val': valid_accu * 100}, epoch_i)
        #     tb_writer.add_scalar('learning_rate', lr, epoch_i)


def main():
    DATASET = "FLICKER"
    with open('./config/config.yml', 'r') as f:
        cfg = yaml.load(f, Loader=yaml.FullLoader)
        cfg = {**cfg[DATASET], **cfg["PARAMS"]}

    paths = {
        "image_path": cfg['IMG_PATH'],
        "text_path": cfg["TXT_PATH"],
        "cap_file": cfg["CAP_FILE"],
        "img_name": cfg["IMG_NAME"],
        "dataset": cfg["DATASET_NAME"],
        "cfg": cfg
    }

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    data = dataset(**paths)
    training_data = DataLoader(data, cfg['BATCH_SIZE'], shuffle=True)

    transformer = Transformer(
        data.encoder.vocab_size,
        trg_pad_idx=0,
        trg_emb_prj_weight_sharing=True,
        d_k=64, d_v=64,
        d_model=512,
        dff=2048, n_layers=1,
        n_head=8,
        dropout=0.1
    ).to(device)

    optimizer = ScheduledOptimizer(
        optim.Adam(transformer.parameters(), betas=(0.9, 0.98), eps=1e-09),
        cfg["LR_MUL"], cfg["D_MODEL"], cfg["WARMUP_STEP"])

    train(transformer, training_data, None, optimizer, device, cfg, data)


if __name__ == '__main__':
    main()
