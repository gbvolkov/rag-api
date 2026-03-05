from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name


PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PPTX_FILE = "Digitme Презентация.pptx"


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "15-pptx-unsupported", "title": "PPTX unsupported workflow", "status": "error"}
    section = 1

    print_section(section, "Create project")
    project = api.create_project(project_name("15-pptx-unsupported"), description=artifacts["title"])
    project_id = project["project_id"]
    artifacts["project_id"] = project_id
    print_kv("Project created", {"project_id": project_id})
    section += 1

    try:
        print_section(section, "Upload PPTX and trigger unsupported loader")
        source_path = docs_path(PPTX_FILE)
        upload = api.upload_document(project_id, source_path, PPTX_MIME)
        document_id = upload["document"]["document_id"]
        document_version_id = upload["document_version"]["version_id"]
        artifacts["document_id"] = document_id
        artifacts["document_version_id"] = document_version_id
        print_kv(
            "Document uploaded",
            {"filename": source_path.name, "document_id": document_id, "document_version_id": document_version_id},
        )
        api.load_documents(document_version_id, loader_type="pptx", loader_params={})
    except ApiClientError as exc:
        artifacts["error_status_code"] = exc.status_code
        artifacts["error_payload"] = exc.payload
        print_api_error(exc)
    else:
        artifacts["status"] = "ok"
        print_kv("Loader result", {"warning": "pptx loader unexpectedly succeeded"})

    section += 1
    export_results_json(api, artifacts["project_id"], artifacts["example_id"])
    print_section(section, "Artifacts saved")
    print_kv("Artifacts", artifacts)
    return artifacts


if __name__ == "__main__":
    run_example()
