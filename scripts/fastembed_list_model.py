from fastembed import TextEmbedding


def list_fastembed_models():
    models = TextEmbedding.list_supported_models()

    if not models:
        print("Нет доступных моделей (проверь сеть или кэш).")
        return

    # Подбираем ширину колонок
    print(f"{'Модель':<55} {'Размерность':<12} {'Размер (GB)':<12} {'Описание'}")
    print("-" * 110)

    for m in models:
        name = m.get("model", "Неизвестно")
        dim = m.get("dim", "?")
        size = m.get("size_in_GB", "?")
        desc = m.get("description", "Без описания")

        # Форматируем размер: если число — оставляем 1 знак после запятой, иначе как есть
        if isinstance(size, (int, float)):
            size_str = f"{size:.1f}"
        else:
            size_str = str(size)

        print(f"{name:<55} {str(dim):<12} {size_str:<12} {desc}")


if __name__ == "__main__":
    list_fastembed_models()
