from pathlib import Path

import mb_crawl


def test_mapped_project_candidates_require_exact_residential_area_name():
    projects = [
        {"name": "Buena Monte Society", "mb_id": "1"},
        {"name": "Buena Monte", "mb_id": "2"},
        {"name": "Unmapped Project", "mb_id": "3"},
    ]
    areas = [{"properties": {"name": "Buena Monte Society"}}]

    assert mb_crawl.mapped_project_candidates(projects, areas) == [projects[0]]


def test_project_cache_path_is_stable_and_uses_the_requested_cache_dir(tmp_path: Path):
    url = "https://example.test/project/1"

    first = mb_crawl.project_cache_path(url, tmp_path)
    second = mb_crawl.project_cache_path(url, tmp_path)

    assert first == second
    assert first.parent == tmp_path
