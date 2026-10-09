---
language:
  - en
  - ar
tags:
- translation
license: cc-by-4.0
inference: false
---

## HPLT MT release v1.0

This repository contains the translation model for English-Arabic trained with OPUS and HPLT data. The model is available in both Marian and Hugging Face formats.

### Model Info

* Source language: English
* Target language: Arabic
* Dataset: OPUS and HPLT data
* Model architecture: Transformer-base
* Tokenizer: SentencePiece (Unigram)
* Cleaning: We used [OpusCleaner](https://github.com/hplt-project/OpusCleaner) with a set of basic rules. Details can be found in the filter files [here](https://github.com/hplt-project/HPLT-MT-Models/tree/main/v1.0/data/ar-en/raw/v2).

You can check out our [deliverable report](https://hplt-project.org/HPLT_D5_1___Translation_models_for_select_language_pairs.pdf), [GitHub repository](https://github.com/hplt-project/HPLT-MT-Models/tree/main/v1.0), and [website](https://hplt-project.org) for more details.

### Usage


The model has been trained with [MarianNMT](https://github.com/marian-nmt/marian) and the weights are in the Marian format. We have also converted the model into the Hugging Face format so it is compatible with `transformers`.

#### Using Marian
To run inference with MarianNMT, refer to the [Inference/Decoding/Translation](https://github.com/hplt-project/HPLT-MT-Models/tree/main/v1.0#inferencedecodingtranslation) section of our GitHub repository. You will need the model file `model.npz.best-chrf.npz` and the vocabulary file `model.en-ar.spm` from this repository.

#### Using transformers
We have also converted this model to the Hugging Face format and you can get started with the script below. **Note** that due a [known issue](https://github.com/huggingface/transformers/issues/26216) in weight conversion, the checkpoint cannot work with transformer versions <4.26 or >4.30. We tested and suggest `pip install transformers==4.28`.

```
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

tokenizer = AutoTokenizer.from_pretrained("HPLT/translate-en-ar-v1.0-hplt_opus")
model = AutoModelForSeq2SeqLM.from_pretrained("HPLT/translate-en-ar-v1.0-hplt_opus")

inputs = ["Input goes here.", "Make sure the language is right."]
batch_tokenized = tokenizer(inputs, return_tensors="pt", padding=True)
model_output = model.generate(
    **batch_tokenized, num_beams=6, max_new_tokens=512
)
batch_detokenized = tokenizer.batch_decode(
    model_output,
    skip_special_tokens=True,
)

print(batch_detokenized)
```

### Benchmarks

When decoded using Marian, the model has the following test scores.

| Test set                               | BLEU | chrF++ | COMET22 |
| -------------------------------------- | ---- | ----- | ----- |
| FLORES200     | 29.2 | 56.9  | 0.8542  |
| NTREX | 25.8   | 52.2  | 0.8245  |

### Acknowledgements

This project has received funding from the European Union's Horizon Europe research and innovation programme under grant agreement No 101070350 and from UK Research and Innovation (UKRI) under the UK government's Horizon Europe funding guarantee [grant number 10052546]

Brought to you by researchers from the University of Edinburgh and Charles University in Prague with support from the whole HPLT consortium.
