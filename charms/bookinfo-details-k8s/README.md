# bookinfo-details-k8s

The Details microservice charm for the Istio [Bookinfo] sample application. It is
used as a test fixture for the Charmed Istio service mesh end-to-end tests in this
repository (`tests/integration/istio`).

## Shared module: `bookinfo_service`

The bookinfo charms talk to each other over a small internal helper,
`src/bookinfo_service.py` (`BookinfoServiceProvider` / `BookinfoServiceConsumer`).

This is **not a Charmhub-published charm library** — it is an ordinary Python module
bundled directly in each charm's `src/` directory and imported as
`from bookinfo_service import ...`. It is intentionally kept out of `lib/charms/` so
it is not picked up by `charmcraft fetch-lib` / the repository's charm-library tooling.

Because the bookinfo charms are only ever deployed together from this repository, the
module is simply duplicated in each charm. When editing it, keep the copies in
`bookinfo-details-k8s` and `bookinfo-productpage-k8s` identical.

[Bookinfo]: https://istio.io/latest/docs/examples/bookinfo/
