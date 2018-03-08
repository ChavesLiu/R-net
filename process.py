# -*- coding: utf-8 -*-
#/usr/bin/python2

import cPickle as pickle
import numpy as np
import json
import codecs
import unicodedata
import re
import sys
import os
import argparse

from tqdm import tqdm
from params import Params

reload(sys)
sys.setdefaultencoding('utf8')

def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

parser = argparse.ArgumentParser()
parser.add_argument('-p','--process', default = False, type = str2bool, help='Use the coreNLP tokenizer.', required=False)
parser.add_argument('-r','--reduce_glove', default = False, type = str2bool, help='Reduce glove size.', required=False)
args = parser.parse_args()

import spacy
nlp = spacy.blank('en')

def tokenize(text):
    parsed = nlp(text)
    tokens = [i.text for i in parsed]
    return tokens

class data_loader(object):
    def __init__(self,use_pretrained = None):
        self.c_dict = {"_UNK":0, "_PAD":1}
        self.w_dict = {"_UNK":0, "_PAD":1}
        self.w_occurence = 0
        self.c_occurence = 0
        self.w_count = 2
        self.c_count = 2
        self.w_unknown_count = 0
        self.c_unknown_count = 0
        self.append_dict = True
        self.invalid_q = 0

        if use_pretrained:
            self.append_dict = False
            self.w_dict, self.w_count = self.process_glove(Params.glove_dir, self.w_dict, self.w_count, Params.emb_size)
            self.c_dict, self.c_count = self.process_glove(Params.glove_char, self.c_dict, self.c_count, 300)
            self.ids2word = {v: k for k, v in self.w_dict.iteritems()}
            self.ids2char = {v: k for k, v in self.c_dict.iteritems()}

    def ind2word(self,ids):
        output = []
        for i in ids:
            output.append(str(self.ids2word[i]))
        return " ".join(output)

    def ind2char(self,ids):
        output = []
        for i in ids:
            for j in i:
                output.append(str(self.ids2char[j]))
            output.append(" ")
        return "".join(output)

    def process_glove(self, wordvecs, dict_, count, emb_size):
        print("Reading GloVe from: {}".format(wordvecs))
        with codecs.open(wordvecs,"rb","utf-8") as f:
            line = f.readline()
            i = 0
            while line:
                vocab = line.split(" ")
                if len(vocab) != emb_size + 1:
                    line = f.readline()
                    continue
                vocab = normalize_text(''.join(vocab[0:-emb_size]).decode("utf-8"))
                if vocab not in dict_:
                    dict_[vocab] = count
                line = f.readline()
                count += 1
                i += 1
                if i % 100 == 0:
                    sys.stdout.write("\rProcessing line %d       "%i)
            print("")
        return dict_, count

    def process_json(self,file_dir,out_dir, write_ = True):
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        self.data = json.load(codecs.open(file_dir,"rb","utf-8"))
        self.loop(self.data, out_dir, write_ = write_)
        with codecs.open("dictionary.txt","wb","utf-8") as f:
            for key, value in sorted(self.w_dict.iteritems(), key=lambda (k,v): (v,k)):
                f.write("%s: %s" % (key, value) + "\n")

    def loop(self, data, dir_ = Params.train_dir, write_ = True):
        for topic in tqdm(data['data'],total = len(data['data'])):
            for para in topic['paragraphs']:
                context = para['context']
                context = context.replace("''", '" ').replace("``", '" ')
                context_tokens = tokenize(context)
                spans = convert_idx(context, context_tokens)

                words_c,chars_c = self.add_to_dict(context_tokens)
                if len(words_c) >= Params.max_p_len:
                    continue

                for qas in para['qas']:
                    question = tokenize(qas['question'].replace("''", '" ').replace("``", '" '))
                    words,chars = self.add_to_dict(question)
                    if len(words) >= Params.max_q_len:
                        continue
                    ans = tokenize(qas['answers'][0]['text'])
                    ans_ids,_ = self.add_to_dict(ans)
                    for answer in qas['answers']:
                        answer_text = answer["text"]
                        answer_start = answer['answer_start']
                        answer_end = answer_start + len(answer_text)
                        answer_span = []
                        for idx, span in enumerate(spans):
                            if not (answer_end <= span[0] or answer_start >= span[1]):
                                answer_span.append(idx)
                        y1, y2 = answer_span[0], answer_span[-1]
                        if write_:
                            write_file([str(y1),str(y2)],dir_ + Params.target_dir)
                            write_file(words,dir_ + Params.q_word_dir)
                            write_file(chars,dir_ + Params.q_chars_dir)
                            write_file(words_c,dir_ + Params.p_word_dir)
                            write_file(chars_c,dir_ + Params.p_chars_dir)

    def process_word(self,line):
        for word in line:
            word = word.replace(" ","").strip()
            word = normalize_text(''.join(word).decode("utf-8"))
            if word:
                if not word in self.w_dict:
                    self.w_dict[word] = self.w_count
                    self.w_count += 1

    def process_char(self,line):
        for char in line.strip():
            if char:
                if char != " ":
                    if not char in self.c_dict:
                        self.c_dict[char] = self.c_count
                        self.c_count += 1

    def add_to_dict(self, line):

        if self.append_dict:
            self.process_word(line)
            self.process_char("".join(line))

        words = []
        chars = []
        count = 0
        for i,word in enumerate(line):
            word = normalize_text(''.join(word).decode("utf-8"))
            if word:
                if count > 0:
                    chars.append("_SPC")
                for char in word:
                    char = self.c_dict.get(char,self.c_dict["_UNK"])
                    chars.append(str(char))
                    self.c_occurence += 1
                    if char == 0:
                        self.c_unknown_count += 1

                count += 1
                word = self.w_dict.get(word.strip().strip(" "),self.w_dict["_UNK"])
                words.append(str(word))
                self.w_occurence += 1
                if word == 0:
                    self.w_unknown_count += 1
            else:
                print("skipped word:{}".format(word))
        return (words, chars)

def load_glove(dir_, name, vocab_size):
    glove = np.zeros((vocab_size,Params.emb_size),dtype = np.float32)
    with codecs.open(dir_,"rb","utf-8") as f:
        line = f.readline()
        i = 1
        while line:
            if i % 100 == 0:
                sys.stdout.write("\rProcessing %d vocabs    "%i)
            vector = line.split(" ")
            if len(vector) != Params.emb_size + 1:
                line = f.readline()
                continue
            vector = vector[-Params.emb_size:]
            if vector:
                try:
                    vector = [float(n) for n in vector]
                except:
                    assert 0
                vector = np.asarray(vector, np.float32)
                try:
                    glove[i] = vector
                except:
                    assert 0
            line = f.readline()
            i += 1
    print("\n")
    glove_map = np.memmap(Params.data_dir + name + ".np", dtype='float32', mode='write', shape=(vocab_size,Params.emb_size))
    glove_map[:] = glove
    del glove_map

def reduce_glove(dir_, dict_):
    glove_f = []
    with codecs.open(dir_, "rb", "utf-8") as f:
        line = f.readline()
        i = 0
        while line:
            i += 1
            if i % 100 == 0:
                sys.stdout.write("\rProcessing %d vocabs    "%i)
            vector = line.split(" ")
            if len(vector) != Params.emb_size + 1:
                line = f.readline()
                continue
            vocab = normalize_text(''.join(vector[0:-Params.emb_size]).decode("utf-8"))
            if vocab not in dict_:
                line = f.readline()
                continue
            glove_f.append(line)
            line = f.readline()
    print("\nTotal number of lines: {}\nReduced vocab size: {}".format(i, len(glove_f)))
    with codecs.open(dir_, "wb", "utf-8") as f:
        i = 1
        for line in glove_f[:-1]:
            f.write(line)
        f.write(glove_f[-1].strip("\n"))
        if i % 100 == 0:
            sys.stdout.write("\rProcessing %d vocabs    "%i)
        i += 1

def convert_idx(text, tokens):
    current = 0
    spans = []
    for token in tokens:
        current = text.find(token, current)
        if current < 0:
            print(text)
            print("Token {} cannot be found".format(token))
            raise Exception()
        spans.append((current, current + len(token)))
        current += len(token)
    return spans

def find_answer_index(context, answer):
    window_len = len(answer)
    answers = []
    if window_len == 1:
        indices = [i for i, ctx in enumerate(context) if ctx == answer[0]]
        for i in indices:
            answers.append((i,i))
        if not indices:
            answers.append((-1,-1))
        return answers
    for i in range(len(context)):
        if context[i:i+window_len] == answer:
            answers.append((i, i + window_len))
    if len(answers) == 0:
        return [(-1, -1)]
    else:
        return answers

def normalize_text(text):
    return unicodedata.normalize('NFD', text)

def write_file(indices, dir_, separate = "\n"):
    with codecs.open(dir_,"ab","utf-8") as f:
        f.write(" ".join(indices) + separate)

def pad_data(data, max_word):
    padded_data = np.ones((len(data),max_word),dtype = np.int32)
    for i,line in enumerate(data):
        for j,word in enumerate(line):
            if j >= max_word:
                break
            padded_data[i,j] = word
    return padded_data

def pad_char_len(data, max_word, max_char):
    padded_data = np.ones((len(data), max_word), dtype=np.int32)
    for i, line in enumerate(data):
        for j, word in enumerate(line):
            if j >= max_word:
                break
            padded_data[i, j] = word if word <= max_char else max_char
    return padded_data

def pad_char_data(data, max_char, max_words):
    padded_data = np.ones((len(data),max_words,max_char),dtype = np.int32)
    for i,line in enumerate(data):
        for j,word in enumerate(line):
            if j >= max_words:
                break
            for k,char in enumerate(word):
                if k >= max_char:
                    # ignore the rest of the word if it's longer than the limit
                    break
                padded_data[i,j,k] = char
    return padded_data

def load_target(dir):
    data = []
    count = 0
    with codecs.open(dir,"rb","utf-8") as f:
        line = f.readline()
        while count < 1000 if Params.mode == "debug" else line:
            line = [int(w) for w in line.split()]
            data.append(line)
            count += 1
            line = f.readline()
    return data

def load_word(dir):
    data = []
    w_len = []
    count = 0
    with codecs.open(dir,"rb","utf-8") as f:
        line = f.readline()
        while count < 1000 if Params.mode == "debug" else line:
            line = [int(w) for w in line.split()]
            if line:
                data.append(line)
                w_len.append(len(line))
            else:
                print(count)
            count += 1
            line = f.readline()
    return data, w_len

def load_char(dir):
    data = []
    w_len = []
    c_len_ = []
    count = 0
    with codecs.open(dir,"rb","utf-8") as f:
        line = f.readline()
        while count < 1000 if Params.mode == "debug" else line:
            c_len = []
            chars = []
            line = line.split("_SPC")
            for word in line:
                c = [int(w) for w in word.split()]
                if c:
                    c_len.append(len(c))
                    chars.append(c)
                else:
                    print(count, dir)
            data.append(chars)
            line = f.readline()
            count += 1
            c_len_.append(c_len)
            w_len.append(len(c_len))
    return data, c_len_, w_len

def max_value(inputlist):
    max_val = 0
    for list_ in inputlist:
        for val in list_:
            if val > max_val:
                max_val = val
    return max_val

def main():
    if args.reduce_glove:
        print("Reducing Glove Matrix")
        loader = data_loader(use_pretrained = False)
        loader.process_json(Params.data_dir + "train-v1.1.json", out_dir = Params.train_dir, write_ = False)
        loader.process_json(Params.data_dir + "dev-v1.1.json", out_dir = Params.dev_dir, write_ = False)
        reduce_glove(Params.glove_dir, loader.w_dict)
    if args.process:
        with open(Params.data_dir + 'dictionary.pkl','wb') as dictionary:
            loader = data_loader(use_pretrained = True)
            print("Tokenizing training data.")
            loader.process_json(Params.data_dir + "train-v1.1.json", out_dir = Params.train_dir)
            print("Tokenizing dev data.")
            loader.process_json(Params.data_dir + "dev-v1.1.json", out_dir = Params.dev_dir)
            loader.vocab_size = max(loader.ids2word.keys()) + 1
            pickle.dump(loader, dictionary, pickle.HIGHEST_PROTOCOL)
            print("Tokenizing complete")
    if os.path.isfile(Params.data_dir + "glove.np"): exit()
    load_glove(Params.glove_dir,"glove",vocab_size = loader.w_count)
    load_glove(Params.glove_char,"glove_char", vocab_size = loader.c_count)
    print("Processing complete")
    print("Unknown word ratio: {} / {}".format(loader.w_unknown_count,loader.w_occurence))
    print("Unknown character ratio: {} / {}".format(loader.c_unknown_count,loader.c_occurence))

if __name__ == "__main__":
    main()
