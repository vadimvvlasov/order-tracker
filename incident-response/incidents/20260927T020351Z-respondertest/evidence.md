# Evidence

- Endpoint: `not given in alert`
- Window: last 15 minutes
- Deployed version(s): dev
- Failing paths: none found

## Requests by route and status (Prometheus)

- `/api/orders/{order_id}` status 200: 0.0 (version dev)
- `/api/orders/{order_id}` status 404: 3.0 (version dev)
- `/api/orders/{order_id}` status 500: 1.0 (version dev)

## Warning and error logs (Loki)

- ERROR request failed path=None status=500 trace_id=e0eb7adfcccbc39df8e69d3799412918 exception=ValueError: day is out of range for month

```text
Traceback (most recent call last):
  File "/app/app/telemetry.py", line 134, in record_request
    response = await call_next(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/starlette/middleware/base.py", line 173, in call_next
    raise app_exc from app_exc.__cause__ or app_exc.__context__
  File "/app/.venv/lib/python3.12/site-packages/starlette/middleware/base.py", line 149, in coro
    await self.app(scope, receive_or_disconnect, send_no_error)
  File "/app/.venv/lib/python3.12/site-packages/starlette/middleware/exceptions.py", line 63, in __call__
    await wrap_app_handling_exceptions(self.app, conn)(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/app/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/app/.venv/lib/python3.12/site-packages/fastapi/middleware/asyncexitstack.py", line 18, in __call__
    await self.app(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/starlette/routing.py", line 676, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 2734, in app
    await route.handle(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 1281, in handle
    await super().handle(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/starlette/routing.py", line 282, in handle
    await self.app(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 158, in app
    await wrap_app_handling_exceptions(app, request)(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/app/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 144, in app
    response = await f(request)
               ^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 706, in app
    raw_response = await run_endpoint_function(
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 354, in run_endpoint_function
    return await run_in_threadpool(dependant.call, **values)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/starlette/concurrency.py", line 34, in run_in_threadpool
    return await anyio.to_thread.run_sync(func)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/anyio/to_thread.py", line 65, in run_sync
    return await get_async_backend().run_sync_in_worker_thread(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/anyio/_backends/_asyncio.py", line 2706, in run_sync_in_worker_thread
    return await future
           ^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/anyio/_backends/_asyncio.py", line 1100, in run
    result = context.run(func, *args)
             ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/app/main.py", line 114, in get_order
    order = order_detail(row)
            ^^^^^^^^^^^^^^^^^
  File "/app/app/main.py", line 60, in order_detail
    estimated_at = placed_at.replace(day=placed_at.day + 2)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ValueError: day is out of range for month
```

- ERROR request failed path=None status=500 trace_id=2b2a63af4d8e576302644381214e9cf4 exception=ValueError: day is out of range for month

```text
Traceback (most recent call last):
  File "/app/app/telemetry.py", line 134, in record_request
    response = await call_next(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/starlette/middleware/base.py", line 173, in call_next
    raise app_exc from app_exc.__cause__ or app_exc.__context__
  File "/app/.venv/lib/python3.12/site-packages/starlette/middleware/base.py", line 149, in coro
    await self.app(scope, receive_or_disconnect, send_no_error)
  File "/app/.venv/lib/python3.12/site-packages/starlette/middleware/exceptions.py", line 63, in __call__
    await wrap_app_handling_exceptions(self.app, conn)(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/app/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/app/.venv/lib/python3.12/site-packages/fastapi/middleware/asyncexitstack.py", line 18, in __call__
    await self.app(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/starlette/routing.py", line 676, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 2734, in app
    await route.handle(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 1281, in handle
    await super().handle(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/starlette/routing.py", line 282, in handle
    await self.app(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 158, in app
    await wrap_app_handling_exceptions(app, request)(scope, receive, send)
  File "/app/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/app/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 144, in app
    response = await f(request)
               ^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 706, in app
    raw_response = await run_endpoint_function(
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 354, in run_endpoint_function
    return await run_in_threadpool(dependant.call, **values)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/starlette/concurrency.py", line 34, in run_in_threadpool
    return await anyio.to_thread.run_sync(func)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/anyio/to_thread.py", line 65, in run_sync
    return await get_async_backend().run_sync_in_worker_thread(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/anyio/_backends/_asyncio.py", line 2706, in run_sync_in_worker_thread
    return await future
           ^^^^^^^^^^^^
  File "/app/.venv/lib/python3.12/site-packages/anyio/_backends/_asyncio.py", line 1100, in run
    result = context.run(func, *args)
             ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/app/main.py", line 114, in get_order
    order = order_detail(row)
            ^^^^^^^^^^^^^^^^^
  File "/app/app/main.py", line 60, in order_detail
    estimated_at = placed_at.replace(day=placed_at.day + 2)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ValueError: day is out of range for month
```


## Error traces (Tempo)

- trace `e0eb7adfcccbc39df8e69d3799412918` GET /api/orders/{order_id} (9 ms)
  - span `GET /api/orders/{order_id}` STATUS_CODE_ERROR {"http.response.status_code": "500", "http.request.method": "GET", "http.route": "/api/orders/{order_id}"}
    - event exception: ValueError: day is out of range for month
  - span `order.lookup` STATUS_CODE_ERROR {"order.id": "express-1002", "order.found": true, "order.priority": "express"}
    - event exception: ValueError: day is out of range for month
- trace `2b2a63af4d8e576302644381214e9cf4` GET /api/orders/{order_id} (12 ms)
  - span `GET /api/orders/{order_id}` STATUS_CODE_ERROR {"http.response.status_code": "500", "http.request.method": "GET", "http.route": "/api/orders/{order_id}"}
    - event exception: ValueError: day is out of range for month
  - span `order.lookup` STATUS_CODE_ERROR {"order.id": "express-1002", "order.found": true, "order.priority": "express"}
    - event exception: ValueError: day is out of range for month

## Recent commits

- 43e115a 2026-09-27T07:02:32+05:00 feat(alerting): add Grafana alert for 5xx responses per endpoint
- a060a4b 2026-09-27T06:53:57+05:00 feat(observability): add Collector, Prometheus, Loki, Tempo, and Grafana
- ff1a0c1 2026-09-27T06:48:22+05:00 feat(telemetry): add OpenTelemetry metrics, traces, and logs for order lookups
- 72de447 2026-09-25T18:46:35+02:00 Simplify local Compose startup
- 9f61e92 2026-09-25T11:17:44+02:00 Add order tracker starter
