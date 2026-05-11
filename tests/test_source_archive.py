from __future__ import annotations

from pathlib import Path

from senior_exam_writer_lib.source_archive import archive_original_sources, connector_for_path


def test_connector_for_path_uses_file_type_specific_reader() -> None:
    assert connector_for_path(Path("a.pdf"))["connector"] == "pdf_reader"
    assert connector_for_path(Path("a.docx"))["connector"] == "docx_reader"
    assert connector_for_path(Path("a.epub"))["connector"] == "epub_reader"
    assert connector_for_path(Path("a.md"))["connector"] == "markdown_reader"
    assert connector_for_path(Path("a.txt"))["connector"] == "text_reader"
    assert connector_for_path(Path("a.jsonl"))["connector"] == "jsonl_reader"


def test_archive_original_sources_preserves_relative_structure(tmp_path) -> None:
    root = tmp_path / "materials"
    nested = root / "course" / "chapter1"
    nested.mkdir(parents=True)
    source = nested / "lesson.txt"
    source.write_text("中文原文", encoding="utf-8")
    archive_dir = tmp_path / "archive"

    records = archive_original_sources([source], [root], archive_dir)

    record = records[str(source.resolve())]
    assert record["archive_relative_path"].replace("\\", "/") == "course/chapter1/lesson.txt"
    archived = archive_dir / "course" / "chapter1" / "lesson.txt"
    assert archived.read_text(encoding="utf-8") == "中文原文"
    assert record["connector_plan"]["connector"] == "text_reader"


def test_archive_original_sources_preserves_chinese_filenames(tmp_path) -> None:
    root = tmp_path / "材料库"
    nested = root / "第一章"
    nested.mkdir(parents=True)
    source = nested / "高等数学材料.md"
    source.write_text("# 样本方差\n中文内容", encoding="utf-8")
    archive_dir = tmp_path / "归档"

    records = archive_original_sources([source], [root], archive_dir)

    record = records[str(source.resolve())]
    assert record["archive_relative_path"].replace("\\", "/") == "第一章/高等数学材料.md"
    assert (archive_dir / "第一章" / "高等数学材料.md").read_text(encoding="utf-8") == "# 样本方差\n中文内容"
    assert record["connector_plan"]["connector"] == "markdown_reader"
