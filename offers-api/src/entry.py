from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from workers import Response, WorkerEntrypoint

from bank_filters import parse_bank_filter
from offer_freshness import cutoff_timestamp, offer_query


CORS_HEADERS = {"Access-Control-Allow-Origin": "*"}
def json_response(
    data,
    status: HTTPStatus = HTTPStatus.OK,
    headers: dict[str, str] | None = None,
) -> Response:
    response_headers = {**CORS_HEADERS, **(headers or {})}
    return Response.json(data, status=status, headers=response_headers)


def normalize_domain(value: str) -> str:
    domain = value.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.split("/", maxsplit=1)[0]


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if request.method.value == "OPTIONS":
            return Response(status=HTTPStatus.NO_CONTENT, headers=CORS_HEADERS)

        url = urlsplit(request.url)
        if request.method.value != "GET":
            return json_response({"error": "Method not allowed"}, HTTPStatus.METHOD_NOT_ALLOWED)

        if url.path == "/health":
            return json_response({"status": "ok"})

        if url.path == "/v1/banks":
            results = await self.env.offers_db.prepare(
                "SELECT slug, name, offers_url FROM banks ORDER BY name"
            ).all()
            return json_response(
                results.results,
                headers={"Cache-Control": "public, max-age=300, s-maxage=300"},
            )

        if url.path != "/v1/offers":
            return json_response({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        parameters = parse_qs(url.query, keep_blank_values=True)
        domain_values = parameters.get("domain", [])
        domain = normalize_domain(domain_values[0]) if domain_values else ""
        if not domain:
            return json_response({"error": "domain is required"}, HTTPStatus.BAD_REQUEST)

        try:
            bank_slugs = parse_bank_filter(parameters.get("banks"))
        except ValueError as error:
            return json_response({"error": str(error)}, HTTPStatus.BAD_REQUEST)

        cutoff = cutoff_timestamp()
        results = await self.env.offers_db.prepare(offer_query(bank_slugs)).bind(
            domain, cutoff, cutoff, domain, *(bank_slugs or [])
        ).all()
        return json_response(
            results.results,
            headers={"Cache-Control": "no-store"},
        )
