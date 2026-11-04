"""Dịch thử offline với model Marian + LoRA đã train trên Colab.
Chạy: python translate_local.py
"""
from pathlib import Path
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from peft import PeftModel

BASE = "Helsinki-NLP/opus-mt-en-vi"
ADAPTER = Path(__file__).resolve().parent / "novel_lora_adapter"
if not ADAPTER.exists():
    raise SystemExit("Hãy giải nén novel_lora_adapter.zip thành thư mục novel_lora_adapter")

tokenizer = AutoTokenizer.from_pretrained(BASE)
base = AutoModelForSeq2SeqLM.from_pretrained(BASE)
model = PeftModel.from_pretrained(base, str(ADAPTER))
model.eval()

text = 'Hello, Yuuka. Where are you! Are you okay?'
inputs = tokenizer(">>vie<< " + text, return_tensors="pt", truncation=True, max_length=256)
with torch.inference_mode():
    output = model.generate(**inputs, max_new_tokens=180, num_beams=4)
print("EN:", text)
print("VI:", tokenizer.decode(output[0], skip_special_tokens=True))
