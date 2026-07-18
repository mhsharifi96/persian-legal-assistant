# Hami Vakil source contract

Observed on 2026-07-17 from the public professional directory at
`https://search-hamivakil.ir/`.

## Request

- Bootstrap a cookie session with `GET /`.
- Send one sequential `POST` to
  `/App/Handler/Lawyer.ashx?Method=mGetLawyerData` per selected bar.
- Use JSON content type and `X-Requested-With: XMLHttpRequest`.
- Send empty search fields and the selected source bar ID as `Bar`:

```json
{
  "license": "",
  "name": "",
  "family": "",
  "nat": "",
  "mob": "",
  "oftel": "",
  "Bar": "<source-bar-id>",
  "add": "",
  "deg": "",
  "pay": ""
}
```

Do not populate `nat`, `mob`, or phone-search fields for bulk collection.

## Observed response

The response is a JSON array. A sampled object contained:

```text
id: string
personNumber: string
name: string
family: string
sex: string
mobileNumber: string
officeAddress: string
RealNameOfState: string
LDBLawyer_To_BITIranLawyerClub_lastLawyerClubId: {name: string}
```

The sampled bar returned exactly 300 records. Treat exactly 300 as potentially
truncated until the source documents its limit or a supported pagination method
is identified. Do not split queries by personal fields merely to work around a
result cap.

## Canonical mapping

```text
lawyer_id        <- "hamivakil:" + id
full_name        <- normalized name + family
specialties      <- [] (not supplied)
location         <- selected bar display name
success_rate     <- 0.0 (not supplied)
metadata.source  <- "search-hamivakil.ir"
metadata.source_record_id <- id
metadata.license_number    <- personNumber
metadata.bar_id / bar_name <- selected bar
metadata.sex               <- sex
metadata.professional_state <- RealNameOfState
metadata.degree            <- nested club.name
metadata.office_address    <- officeAddress
```

Discard `mobileNumber`. The source response did not expose the national-ID
search value in the sampled object, and the fetcher must not request it.

## Blocking and errors

- Stop on HTTP 401, 403, or 429 and preserve the checkpoint.
- Treat an HTML/access page returned with HTTP 200 as a possible stale session:
  clear cookies, bootstrap one fresh session, and retry once. If HTML repeats,
  treat it as blocking and stop.
- Retry a transient empty HTTP 200 response with a fresh session, using the same
  bounded retry limit and stable user agent.
- After all empty-body retries are exhausted, warn and continue to the next bar.
  Do not checkpoint the empty bar as completed, so a resumed run retries it.
- Retry only transient network errors and HTTP 5xx responses, with bounded
  exponential backoff.
- Use one stable, transparent user agent. Never rotate user agents, cookies,
  proxies, IP addresses, or identities to bypass controls.
- Do not automate CAPTCHA solving or reverse-engineer unsupported pagination.
