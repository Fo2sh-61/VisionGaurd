# Contract: the contact form → FormSubmit

The website's only outside call.

## Request

```text
POST https://formsubmit.co/ajax/sales@vision-guard.org
Content-Type: application/json
Accept: application/json
```

```json
{
  "name": "…",
  "email": "…",
  "company": "…",
  "phone": "…",
  "site_type": "Office",
  "cameras": "25–100",
  "message": "…",
  "_subject": "Website enquiry: <company>",
  "_replyto": "<the visitor's email>",
  "_template": "table",
  "_honey": ""
}
```

The page must be served over http(s). FormSubmit uses the page's address, and
refuses a page opened as a file.

## Answer → what the visitor sees

| FormSubmit answers | Page shows |
|---|---|
| HTTP 200, body `{"success":"true", …}` | thank-you (**sent**) |
| HTTP 200, body `{"success":"false", "message": …}`, e.g. the address is not activated yet | **failed** |
| any other status, a body that is not JSON, a network error, or no answer within 15 s | **failed** |

`success` is a string. Compare with `=== "true"` (also accept boolean `true` in case
it changes). FormSubmit's own `message` is never shown to the visitor. It goes to the
browser console for whoever is debugging.
