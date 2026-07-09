import sys

from fastembed import TextEmbedding

if len(sys.argv) != 2:
    print("Использование: python script.py <имя_модели>")
    print("Пример: python script.py sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    sys.exit(1)

model_name = sys.argv[1]

texts = [
    "Привет, как дела?",
    "Где ты сейчас находишься?",
    "Скинь ссылку на тот документ",
    "Не понял, что ты имеешь в виду",
]

print(f"Загружаем модель: {model_name} ...")
model = TextEmbedding(model_name=model_name, quantize=False)  # без квантования

# print(model.__dir__())
print(f"Размерность вектора: {model.embedding_size}")
print("Генерируем эмбеддинги:\n")

for text in texts:
    emb = list(model.embed([text]))[0]  # embed возвращает список, берём первый элемент
    print(f"Текст: {text}")
    print(f"Вектор (первые 5 значений): {emb[:5]}")
    print(f"Тип данных: {emb.dtype}, размер: {emb.nbytes} байт\n")
