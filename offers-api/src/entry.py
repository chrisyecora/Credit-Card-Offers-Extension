from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from workers import Response, WorkerEntrypoint


CORS_HEADERS = {"Access-Control-Allow-Origin": "*"}
OFFER_FIELDS = """
    domain,
    merchant_name,
    reward_rate,
    channel,
    bank,
    logo_url,
    last_seen_at
"""


def json_response(data, status: HTTPStatus = HTTPStatus.OK) -> Response:
    return Response.json(data, status=status, headers=CORS_HEADERS)


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

        if url.path != "/v1/offers":
            return json_response({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        domain_values = parse_qs(url.query).get("domain", [])
        domain = normalize_domain(domain_values[0]) if domain_values else ""
        if not domain:
            return json_response({"error": "domain is required"}, HTTPStatus.BAD_REQUEST)

        query = f"SELECT {OFFER_FIELDS} FROM offers WHERE domain = ?"
        results = await self.env.offers_db.prepare(query).bind(domain).all()
        return json_response(results.results)
