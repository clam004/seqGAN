import sys
from math import ceil

import torch

import helpers


def train_generator_MLE(gen, gen_opt, oracle, real_data_samples, epochs,
    POS_NEG_SAMPLES = 10000,
    BATCH_SIZE = 32,
    START_LETTER = 0,
    MAX_SEQ_LEN = 20,
    CUDA = False,
):

    """
    Max Likelihood Pretraining for the generator
    """

    for epoch in range(epochs):
        print('epoch %d : ' % (epoch + 1), end='')
        sys.stdout.flush()
        total_loss = 0

        for i in range(0, POS_NEG_SAMPLES, BATCH_SIZE):
            inp, target = helpers.prepare_generator_batch(
                real_data_samples[i:i + BATCH_SIZE], 
                start_letter=START_LETTER,
                gpu=CUDA,
            )
            gen_opt.zero_grad()
            loss = gen.batchNLLLoss(inp, target)
            loss.backward()
            gen_opt.step()

            total_loss += loss.data.item()

            # roughly every 10% of an epoch add a period to the progress so 10 periods is one epoch
            if (i / BATCH_SIZE) % ceil(ceil(POS_NEG_SAMPLES / float(BATCH_SIZE)) / 10.) == 0:  
                print('.', end='')
                sys.stdout.flush()

        # each loss in a batch is loss per sample
        total_loss = total_loss / ceil(POS_NEG_SAMPLES / float(BATCH_SIZE)) / MAX_SEQ_LEN

        # sample from generator and compute oracle NLL
        oracle_loss = helpers.batchwise_oracle_nll(
            gen, 
            oracle, 
            POS_NEG_SAMPLES, 
            BATCH_SIZE, MAX_SEQ_LEN,
            start_letter=START_LETTER, 
            gpu=CUDA,
        )

        print(' average_train_NLL = %.4f, oracle_sample_NLL = %.4f' % (total_loss, oracle_loss))


def train_generator_PG(gen, gen_opt, oracle, dis, num_batches,
    POS_NEG_SAMPLES = 10000,
    BATCH_SIZE = 32,
    START_LETTER = 0,
    MAX_SEQ_LEN = 20,
    CUDA = False,
):
    """
    The generator is trained using policy gradients, using the reward from the discriminator.
    Training is done for num_batches batches.
    """

    for batch in range(num_batches):
        s = gen.sample(BATCH_SIZE*2)        # 64 works best
        inp, target = helpers.prepare_generator_batch(s, start_letter=START_LETTER, gpu=CUDA)
        rewards = dis.batchClassify(target)

        gen_opt.zero_grad()
        pg_loss = gen.batchPGLoss(inp, target, rewards)
        pg_loss.backward()
        gen_opt.step()

    # sample from generator and compute oracle NLL
    oracle_loss = helpers.batchwise_oracle_nll(
        gen, 
        oracle, 
        POS_NEG_SAMPLES, 
        BATCH_SIZE, MAX_SEQ_LEN,
        start_letter=START_LETTER, 
        gpu=CUDA,
    )

    print(' oracle_sample_NLL = %.4f' % oracle_loss)


def train_discriminator(discriminator, dis_opt, real_data_samples, generator, oracle, d_steps, epochs,
    POS_NEG_SAMPLES = 10000,
    BATCH_SIZE = 32,
    CUDA = False,
):
    """
    Training the discriminator on real_data_samples (positive) and generated samples from generator (negative).
    Samples are drawn d_steps times, and the discriminator is trained for epochs epochs.
    """

    # generating a small validation set before training (using oracle and generator)
    pos_val = oracle.sample(100)
    neg_val = generator.sample(100)
    val_inp, val_target = helpers.prepare_discriminator_data(pos_val, neg_val, gpu=CUDA)

    for d_step in range(d_steps):
        s = helpers.batchwise_sample(generator, POS_NEG_SAMPLES, BATCH_SIZE)
        dis_inp, dis_target = helpers.prepare_discriminator_data(real_data_samples, s, gpu=CUDA)
        for epoch in range(epochs):
            print('d-step %d epoch %d : ' % (d_step + 1, epoch + 1), end='')
            sys.stdout.flush()
            total_loss = 0
            total_acc = 0

            for i in range(0, 2 * POS_NEG_SAMPLES, BATCH_SIZE):
                inp, target = dis_inp[i:i + BATCH_SIZE], dis_target[i:i + BATCH_SIZE]
                dis_opt.zero_grad()
                out = discriminator.batchClassify(inp)
                loss_fn = torch.nn.BCELoss()
                loss = loss_fn(out, target)
                loss.backward()
                dis_opt.step()

                total_loss += loss.data.item()
                total_acc += torch.sum((out>0.5)==(target>0.5)).data.item()

                if (i / BATCH_SIZE) % ceil(ceil(2 * POS_NEG_SAMPLES / float(
                        BATCH_SIZE)) / 10.) == 0:  # roughly every 10% of an epoch
                    print('.', end='')
                    sys.stdout.flush()

            total_loss /= ceil(2 * POS_NEG_SAMPLES / float(BATCH_SIZE))
            total_acc /= float(2 * POS_NEG_SAMPLES)

            val_pred = discriminator.batchClassify(val_inp)
            print(' average_loss = %.4f, train_acc = %.4f, val_acc = %.4f' % (
                total_loss, total_acc, torch.sum((val_pred>0.5)==(val_target>0.5)).data.item()/200.))