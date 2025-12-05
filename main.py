import re
import sys
from pathlib import Path
import json
import pandas as pd
import requests
from urllib.parse import unquote, urlparse


def extract_history_from_html(html_source: str | Path, dataset_key: str) -> list[dict]:
    """
    Читает history.html через URL или из файла и достаёт данные из объекта DATASETS_HISTORY внутри <script>.

    Формат одного блока в history.html:
        {
          name: "Mesto_jitelstva",
          start: "04.11.2025 20:54",
          end: "04.11.2025 22:14",
          status: "Выполнено",
          count: 456,
        }
    """
    # Если это file:// URL, конвертируем в путь к файлу
    if isinstance(html_source, str) and html_source.startswith("file://"):
        # Декодируем URL и извлекаем путь
        parsed = urlparse(unquote(html_source))
        html_path = Path(parsed.path)
        html_text = html_path.read_text(encoding="utf-8")
    # Если это HTTP/HTTPS URL, делаем запрос
    elif isinstance(html_source, str) and (html_source.startswith("http://") or html_source.startswith("https://")):
        resp = requests.get(html_source)
        resp.raise_for_status()
        html_text = resp.text
    # Иначе читаем из файла (Path или строка-путь)
    elif isinstance(html_source, Path):
        html_text = html_source.read_text(encoding="utf-8")
    else:
        # Если передана строка-путь к файлу
        html_path = Path(html_source)
        html_text = html_path.read_text(encoding="utf-8")

    # Сначала вырезаем блок нужного датасета из DATASETS_HISTORY
    block_pattern = re.compile(
        rf"{re.escape(dataset_key)}\s*:\s*\[(?P<body>.*?)\]",
        re.DOTALL,
    )
    block_match = block_pattern.search(html_text)
    if not block_match:
        raise RuntimeError(f"Не найден блок DATASETS_HISTORY для ключа {dataset_key!r}")

    body = block_match.group("body")

    # Ищем все объекты внутри этого блока
    item_pattern = re.compile(
        r"\{\s*name:\s*\"(?P<name>[^\"]+)\""
        r",\s*start:\s*\"(?P<start>[^\"]+)\""
        r",\s*end:\s*\"(?P<end>[^\"]+)\""
        r",\s*status:\s*\"(?P<status>[^\"]+)\""
        r",\s*count:\s*(?P<count>\d+)\s*,?\s*\}",
        re.MULTILINE,
    )

    result: list[dict] = []
    for match in item_pattern.finditer(body):
        data = match.groupdict()
        result.append(
            {
                "name": data["name"],
                "start_time": data["start"],
                "end_time": data["end"],
                "status": data["status"],
                "records_count": int(data["count"]),
            }
        )

    if not result:
        raise RuntimeError(
            f"Не удалось найти ни одной записи истории для {dataset_key!r} в history.html"
        )

    return result


def main() -> None:
    project_root = Path(__file__).resolve().parent
    
    # URL можно передать как второй аргумент, иначе используется дефолтный localhost
    if len(sys.argv) > 2:
        history_url = sys.argv[2]
        # Если передан file:// URL, автоматически заменяем имя файла на history.html
        if history_url.startswith("file://"):
            parsed = urlparse(unquote(history_url))
            file_path = Path(parsed.path)
            # Заменяем имя файла на history.html, сохраняя путь
            history_path = file_path.parent / "history.html"
            history_url = f"file://{history_path}"
    else:
        # Дефолтный URL для локального сервера
        history_url = "http://localhost:8000/history.html"
    
    dataset_key = sys.argv[1] if len(sys.argv) > 1 else "set1"

    # history: "сырые" записи из HTML (start/end, статус и т.д.) ТОЛЬКО для выбранного набора
    history = extract_history_from_html(history_url, dataset_key)

    # Оставляем только ПОСЛЕДНЮЮ (самую верхнюю в таблице) запись для каждого правила.
    # В history.html записи уже отсортированы по убыванию даты, поэтому берём
    # первый встретившийся элемент для каждого name.
    seen_rules: set[str] = set()
    prepared: list[dict] = []
    for item in history:
        rule_name = item["name"]
        if rule_name in seen_rules:
            continue
        seen_rules.add(rule_name)
        prepared.append(
            {
                "rule_name": rule_name,
                "date": item["start_time"].split(" ")[0],  # из "04.11.2025 20:54" берём "04.11.2025"
                "records_count": item["records_count"],
            }
        )

    # Сохраняем статистику в Excel
    df = pd.DataFrame(prepared)
    output_path = project_root / f"history_stats_{dataset_key}.xlsx"
    df.to_excel(output_path, index=False)

    print(f"Данные ({len(prepared)} строк) для {dataset_key} записаны в {output_path}")


if __name__ == "__main__":
    main()


