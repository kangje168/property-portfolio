"""Machine-readable OpenAPI contract, served without remote UI dependencies."""


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def response(schema, description="Success"):
    return {
        "description": description,
        "content": {"application/json": {"schema": schema}},
    }


def parameter(name, schema, description="", location="query", required=False):
    return {
        "name": name,
        "in": location,
        "required": required,
        "description": description,
        "schema": schema,
    }


def operation(operation_id, summary, schema, *, status="200", params=None, body=None):
    result = {
        "operationId": operation_id,
        "summary": summary,
        "responses": {
            status: response(schema),
            **{
                str(n): response(ref("Error"), d)
                for n, d in [
                    (400, "Invalid input"),
                    (401, "Missing, expired or revoked API key"),
                    (403, "Manager scope or role denied"),
                    (404, "Resource not found"),
                    (413, "Request too large"),
                    (415, "Expected JSON content type"),
                    (429, "API key rate limit exceeded"),
                    (500, "Internal error"),
                ]
            },
        },
    }
    if params:
        result["parameters"] = params
    if body:
        result["requestBody"] = body
    return result


INTEGER = {"type": "integer", "minimum": 1, "maximum": 2147483647}
PAGINATION = [
    parameter(
        "limit", {"type": "integer", "minimum": 1, "maximum": 100, "default": 50}
    ),
    parameter(
        "offset", {"type": "integer", "minimum": 0, "maximum": 1000000, "default": 0}
    ),
]
MANAGER = parameter(
    "manager_id",
    INTEGER,
    "Admin: optional global filter. Other keys: must match their assigned manager.",
)
PROPERTY = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "manager_id",
        "external_id",
        "name",
        "address",
        "city",
        "property_type",
        "bedrooms",
        "price_eur",
        "latitude",
        "longitude",
        "rating",
        "updated_at",
    ],
    "properties": {
        "id": INTEGER,
        "manager_id": INTEGER,
        "external_id": {"type": "string", "maxLength": 80},
        "name": {"type": "string", "maxLength": 120},
        "address": {"type": "string", "maxLength": 240},
        "city": {"type": "string", "maxLength": 100},
        "property_type": {
            "type": "string",
            "enum": ["apartment", "house", "office", "retail"],
        },
        "bedrooms": {"type": "integer", "minimum": 0, "maximum": 20},
        "price_eur": {
            "type": "string",
            "pattern": r"^[0-9]+\.[0-9]{2}$",
            "description": "Exact EUR amount; never a binary float",
        },
        "latitude": {"type": "number", "minimum": -90, "maximum": 90},
        "longitude": {"type": "number", "minimum": -180, "maximum": 180},
        "rating": {"type": "integer", "minimum": 1, "maximum": 5, "nullable": True},
        "updated_at": {"type": "string", "format": "date-time"},
    },
}
PAGE = {
    "type": "object",
    "required": ["items", "total", "limit", "offset"],
    "properties": {
        "items": {"type": "array", "items": ref("Property")},
        "total": {"type": "integer", "minimum": 0},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
        "boundary": {"type": "string", "enum": ["included"]},
    },
}
IMPORT = {
    "type": "object",
    "required": [
        "import_id",
        "manager_id",
        "sha256",
        "rows",
        "created",
        "updated",
        "unchanged",
        "rejected",
        "errors",
    ],
    "properties": {
        "import_id": INTEGER,
        "manager_id": INTEGER,
        "sha256": {"type": "string", "minLength": 64, "maxLength": 64},
        "created_at": {"type": "string", "format": "date-time"},
        **{
            name: {"type": "integer", "minimum": 0}
            for name in ["rows", "created", "updated", "unchanged", "rejected"]
        },
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["record", "error"],
                "properties": {
                    "record": {
                        "type": "integer",
                        "minimum": 2,
                        "description": "CSV record ordinal including header; not physical line number for multiline fields",
                    },
                    "error": {"type": "string"},
                },
            },
        },
    },
}
POLYGON = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "coordinates"],
    "properties": {
        "type": {"type": "string", "enum": ["Polygon"]},
        "coordinates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10,
            "items": {
                "type": "array",
                "minItems": 4,
                "items": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "number"},
                },
            },
        },
    },
    "description": "GeoJSON [longitude, latitude], closed rings, <=1000 positions, no antimeridian span. Boundaries included, hole interiors excluded. Planar lon/lat containment for local portfolios; no geodesic areas.",
}

SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "Property Portfolio API",
        "version": "0.1.0",
        "description": "CSV intake, scoped property search, review ratings and local geographic filtering. No valuation, listing scrape or AI decisions.",
    },
    "servers": [{"url": "/"}],
    "security": [{"ApiKey": []}],
    "components": {
        "securitySchemes": {
            "ApiKey": {
                "type": "http",
                "scheme": "bearer",
                "description": "Expiring opaque API key generated by portfolio key-create; not a JWT",
            }
        },
        "schemas": {
            "Error": {
                "type": "object",
                "required": ["error"],
                "properties": {
                    "error": {"type": "string"},
                    "request_id": {"type": "string"},
                },
            },
            "Property": PROPERTY,
            "PropertyPage": PAGE,
            "ImportReport": IMPORT,
            "Polygon": POLYGON,
        },
    },
    "paths": {
        "/health": {
            "get": {
                "operationId": "health",
                "security": [],
                "responses": {
                    "200": response(
                        {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string", "enum": ["ok"]}
                            },
                        }
                    ),
                    "500": response(ref("Error"), "Database unavailable"),
                },
            }
        },
        "/v1/managers": {
            "get": operation(
                "listManagers",
                "List managers visible to this API key",
                {
                    "type": "object",
                    "required": ["items"],
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["id", "name"],
                                "properties": {
                                    "id": INTEGER,
                                    "name": {"type": "string"},
                                },
                            },
                        }
                    },
                },
            )
        },
        "/v1/properties": {
            "get": operation(
                "searchProperties",
                "Search and paginate the property portfolio",
                ref("PropertyPage"),
                params=[
                    MANAGER,
                    parameter("property_type", PROPERTY["properties"]["property_type"]),
                    parameter(
                        "city", {"type": "string", "maxLength": 100}, "Exact city name"
                    ),
                    parameter("bedrooms", PROPERTY["properties"]["bedrooms"]),
                    *[
                        parameter(
                            n,
                            {"type": "string", "pattern": r"^[0-9]+(\.[0-9]{1,2})?$"},
                            "EUR amount; maximum 1000000000",
                        )
                        for n in ["min_price", "max_price"]
                    ],
                    *PAGINATION,
                ],
            )
        },
        "/v1/imports": {
            "post": operation(
                "importProperties",
                "Upsert CSV records; reject invalid rows with a durable report",
                ref("ImportReport"),
                status="201",
                body={
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["file"],
                                "properties": {
                                    "file": {
                                        "type": "string",
                                        "format": "binary",
                                        "description": "UTF-8 CSV <=2 MiB, <=10000 records",
                                    },
                                    "manager_id": {
                                        **INTEGER,
                                        "description": "Required for an admin, implicit for scoped keys",
                                    },
                                },
                            }
                        }
                    },
                },
            )
        },
        "/v1/imports/{run_id}": {
            "get": operation(
                "getImportReport",
                "Read an import report within the key's scope",
                ref("ImportReport"),
                params=[parameter("run_id", INTEGER, location="path", required=True)],
            )
        },
        "/v1/properties/{property_id}/rating": {
            "patch": operation(
                "rateProperty",
                "Set a human review rating; requires manager or admin",
                ref("Property"),
                params=[
                    parameter("property_id", INTEGER, location="path", required=True)
                ],
                body={
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["rating"],
                                "properties": {
                                    "rating": {
                                        "type": "integer",
                                        "minimum": 1,
                                        "maximum": 5,
                                    }
                                },
                            }
                        }
                    },
                },
            )
        },
        "/v1/properties/search-area": {
            "post": operation(
                "searchArea",
                "Find properties covered by a local GeoJSON polygon",
                ref("PropertyPage"),
                body={
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["geometry"],
                                "properties": {
                                    "geometry": ref("Polygon"),
                                    "manager_id": INTEGER,
                                    "limit": PAGINATION[0]["schema"],
                                    "offset": PAGINATION[1]["schema"],
                                },
                            }
                        }
                    },
                },
            )
        },
    },
}
SPEC["paths"]["/v1/properties/search-area"]["post"]["responses"]["422"] = response(
    ref("Error"), "More than 10000 bounding-box candidates; narrow the area"
)
