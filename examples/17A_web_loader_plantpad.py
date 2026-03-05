from examples.api_client import ApiClientError
from examples.example_utils import default_client, export_results_json, print_api_error, print_kv, print_section, project_name


TARGET_URL = "https://plantpad.samlab.cn/search.html"
CLEANUP_CONFIG = {
    "duplicate_tags": ["div", "p", "table"],
    "non_recursive_classes": ["tag"],
    "navigation_classes": ["menus"],
    "navigation_styles": [],
    "navigation_texts": ["<", ">"],
    "ignored_classes": ["header"],
}
RECURSIVE_SPLITTER_PARAMS = {"chunk_size": 1200, "chunk_overlap": 120}

PLANTPAD_SEED_SCRIPT = """
async ({ keyword }) => {
  const current = new URL(window.location.href);
  if (!current.pathname.endsWith("/search.html")) return false;
  const app = document.querySelector("#app");
  const vm = app && app.__vue__;
  if (!vm) return false;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  if ((!Array.isArray(vm.search_result) || vm.search_result.length === 0) && typeof vm.doSearch === "function") {
    if (keyword && typeof vm.search_context === "string" && !vm.search_context.trim()) {
      vm.search_context = keyword;
      const searchInput = document.querySelector(".search_input");
      if (searchInput) searchInput.value = keyword;
    }
    vm.page = 0;
    vm.doSearch();
    await sleep(900);
  }
  if ((!Array.isArray(vm.search_result) || vm.search_result.length === 0) && typeof vm.getSearchData === "function") {
    vm.page = 0;
    vm.getSearchData();
    await sleep(900);
  }
  return true;
}
"""

PLANTPAD_EXTRACT_SCRIPT = """
() => {
  const current = new URL(window.location.href);
  if (!current.pathname.endsWith("/search.html")) return [];
  const app = document.querySelector("#app");
  const vm = app && app.__vue__;
  if (!vm || !Array.isArray(vm.search_result)) return [];
  const urls = [];
  for (const item of vm.search_result) {
    const rawId = item && (item.img_id ?? item.imgId ?? item.id);
    if (rawId === undefined || rawId === null || rawId === "") continue;
    urls.push(`disease.html?img_id=${encodeURIComponent(String(rawId))}`);
  }
  return urls;
}
"""

PLANTPAD_NEXT_PAGE_SCRIPT = """
() => {
  const current = new URL(window.location.href);
  if (!current.pathname.endsWith("/search.html")) return false;
  const app = document.querySelector("#app");
  const vm = app && app.__vue__;
  if (!vm || typeof vm.nextPage !== "function") return false;
  if (vm.top) return false;
  const before = Number(vm.page || 0);
  vm.nextPage();
  const after = Number(vm.page || 0);
  return after > before;
}
"""


def _playwright_extraction_config() -> dict:
    return {
        "profiles": [
            {
                "profile": "paginated_eval",
                "script_args": {"keyword": ""},
                "seed_script": PLANTPAD_SEED_SCRIPT,
                "extract_script": PLANTPAD_EXTRACT_SCRIPT,
                "next_page_script": PLANTPAD_NEXT_PAGE_SCRIPT,
                "max_pages": 512,
                "wait_after_action_ms": 700,
                "source_tag": "vue-search",
                "source_classes": ["table-button"],
            }
        ]
    }


def _sync_loader_params() -> dict:
    return {
        "url": TARGET_URL,
        "depth": 3,
        "output_format": "markdown",
        "fetch_mode": "playwright",
        "crawl_scope": "same_host",
        "follow_download_links": False,
        "cleanup_config": CLEANUP_CONFIG,
        "playwright_visible": True,
        "playwright_navigation_config": {"enabled": True, "max_clicks": 512, "max_states": 513},
        "playwright_extraction_config": _playwright_extraction_config(),
    }


def _async_loader_params() -> dict:
    params = _sync_loader_params()
    params["max_concurrency"] = 4
    return params


def _segment_preview(segment_items: list[dict]) -> dict:
    if not segment_items:
        return {"items": 0}

    first = segment_items[0]
    return {"items": len(segment_items), "content_preview": (first.get("content") or "")[:120]}


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "17A-web-loader-plantpad", "title": "Web loader plantpad workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("17A-web-loader-plantpad"), description=artifacts["title"])
        project_id = project["project_id"]
        artifacts["project_id"] = project_id
        print_kv("Project created", {"project_id": project_id})
        section += 1

        print_section(section, "Load URL documents (sync web)")
        loaded_sync = api.load_documents_from_url(project_id, loader_type="web", loader_params=_sync_loader_params())
        sync_document_set_version_id = loaded_sync["document_set"]["document_set_version_id"]
        artifacts["document_set_version_id"] = sync_document_set_version_id
        seg_sync = api.create_segments(
            sync_document_set_version_id,
            split_strategy="recursive",
            splitter_params=RECURSIVE_SPLITTER_PARAMS,
        )
        sync_segment_set_version_id = seg_sync["segment_set"]["segment_set_version_id"]
        artifacts["segment_set_version_id"] = sync_segment_set_version_id
        print_kv(
            "URL segments created",
            {
                "document_set_version_id": sync_document_set_version_id,
                "document_items": len(loaded_sync["items"]),
                "segment_set_version_id": sync_segment_set_version_id,
                **_segment_preview(seg_sync["items"]),
            },
        )
        section += 1

        print_section(section, "Load URL documents (async web)")
        loaded_async = api.load_documents_from_url(project_id, loader_type="web_async", loader_params=_async_loader_params())
        async_document_set_version_id = loaded_async["document_set"]["document_set_version_id"]
        artifacts["async_document_set_version_id"] = async_document_set_version_id
        seg_async = api.create_segments(
            async_document_set_version_id,
            split_strategy="recursive",
            splitter_params=RECURSIVE_SPLITTER_PARAMS,
        )
        async_segment_set_version_id = seg_async["segment_set"]["segment_set_version_id"]
        artifacts["async_segment_set_version_id"] = async_segment_set_version_id
        print_kv(
            "URL segments created",
            {
                "document_set_version_id": async_document_set_version_id,
                "document_items": len(loaded_async["items"]),
                "segment_set_version_id": async_segment_set_version_id,
                **_segment_preview(seg_async["items"]),
            },
        )
        section += 1
    except ApiClientError as exc:
        artifacts["status"] = "error"
        artifacts["error_status_code"] = exc.status_code
        artifacts["error_payload"] = exc.payload
        print_api_error(exc)
        raise

    export_results_json(api, artifacts["project_id"], artifacts["example_id"])
    print_section(section, "Artifacts saved")
    print_kv("Artifacts", artifacts)
    return artifacts


if __name__ == "__main__":
    run_example()
