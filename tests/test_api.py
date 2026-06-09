from __future__ import annotations

from fastapi.routing import APIRoute

from eutherbooks.api import create_app


def test_books_endpoint_uses_dependency_not_query_param() -> None:
    app = create_app()

    route = next(route for route in app.routes if isinstance(route, APIRoute) and route.path == "/books")

    assert [param.name for param in route.dependant.query_params] == []


def test_upload_book_endpoint_uses_name_query_param() -> None:
    app = create_app()

    route = next(route for route in app.routes if isinstance(route, APIRoute) and route.path == "/books/upload")

    assert [param.name for param in route.dependant.query_params] == ["name"]
