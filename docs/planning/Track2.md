# Brainstorm Ideas for Track 2

Also, below attached are some ideas given by organizers:

## Organizer Ideas

* **Custom OTel Auto-Instrumentation Library**
  * Build a custom OTel auto-instrumentation library for a framework that lacks one, and contribute it.
* **Cross-Signal Panel for One Service**
* **Query Builder vs PromQL/LogQL**
  * PromQL to BuilderQuery Conversion
* **Multi-Cluster Telemetry**
  * Multi-cluster telemetry on one SigNoz.
  * Multi-cluster/region telemetry routed through the OTel Collector into one self-hosted SigNoz.
* **SLO/Error-Budget Dashboard Pack**
* **Monitor Anything Weird**
  * For example: A Raspberry Pi homelab, 3D printer, Minecraft server, or even a coffee machine instrumented with OTel and a live SigNoz dashboard on a screen at the venue.
* **Personal Observability**
  * For example: Track your own coding sessions, AI agent usage, or app screen time as metrics/traces.
* **Observability Ingested Data Quality Checker (OTel Native)**
  * Use SigNoz MCP to evaluate.

## Database / Query Operations

* **Order By + Limit:** Sorting and ordering the results.
  Every `group by` query can rank its results and keep only the top (or bottom) N.

  **Latency**
  Say you’re building the page-one panel of a service dashboard. 
  _Which 10 endpoints are the slowest right now?_
  ```yaml
  Signal: traces
  Aggregation: p99(duration_nano)
  Group by: http.route
  Order by: p99(duration_nano) desc
  Limit: 10
  ```

  **Which service to investigate first**
  Multiple services are erroring during an incident and you have to pick where to start. 
  _Which services are failing the most right now?_
  ```yaml
  Signal: traces
  Aggregation: countIf(has_error = true)
  Group by: service.name
  Order by: countIf(has_error = true) desc
  Limit: 5
  ```

  **API endpoint deprecation (bottom-N)**
  Say you want to retire endpoints nobody uses and back it by data. 
  _Which endpoints received the least traffic this month?_
  ```yaml
  Signal: traces
  Aggregation: count()
  Group by: http.route
  Order by: count() asc
  Limit: 20
  ```

* **Search:** Filtering the data.
  **Modelling complex filter requirement with search (if/else as a query)**
  Let’s say you are an engineer on a team with non-trivial failure criteria:
  For the checkout service, anything slower than 2s is a failure even if it succeeded; for everything else, only 5xx counts as failure and never count synthetic requests or canaries.
  ```sql
  ((service.name = 'checkout' AND (has_error = true OR duration_nano > 2000000000))
    OR (service.name != 'checkout' AND response_status_code >= 500))
  AND NOT (user_agent CONTAINS 'synthetic' OR k8s.pod.name LIKE '%canary%')
  ```
  Look at the use of parentheses, `OR`, `AND`, and `NOT` combinations to achieve the goal. Flat filter UIs `AND` everything globally, so “a different failure criteria per service” is impossible to model.

  **Querying for what’s missing**
  Let’s say we are interested in fixing the broken telemetry. 
  Trace context propagation is not working after the recent rollout. Which production errors have no trace attached, excluding batch jobs that legitimately run outside one?
  ```sql
  severity_text IN ('ERROR', 'FATAL')
  AND resource.deployment.environment = 'production'
  AND trace_id NOT EXISTS
  AND NOT service.name IN ('cron-runner', 'batch-export')
  ```
  `EXISTS` / `NOT EXISTS` turn absence into a main predicate.

  **Working with Log JSON body**
  Say you’ve put Kafka in front of `signoz-otel-collector` and have a question about retries.
  Find Kafka rebalance loops for our consumer groups where retries crossed the threshold and skip the routine ‘completed’ notices.
  ```sql
  hasToken(body, 'rebalance')
  AND body.consumer_group IN ('orders-cg', 'payments-cg')
  AND body.retry_count > 3
  AND NOT body.message CONTAINS 'completed'
  ```
  This example shows:
  * Token search
  * JSON path access
  * A numeric comparison on a JSON field
  `grep` gives you only the first one.

  **Feature-flag combination debugging**
  Instrument your code to generate active flags as an array attribute, then isolate regressions caused by a specific combination.
  ```sql
  hasAll(feature_flags, ['new-checkout', 'express-pay']) AND has_error = true
  ```
  `hasAll` / `hasAny` / `has` allow you to query array attributes. This is the capability LaunchDarkly-style experiment debugging actually needs, and almost no observability tool has it.

  **Secret leak detection**
  Are secrets or PII data leaking into production logs?
  ```sql
  (body REGEXP 'AKIA[0-9A-Z]{16}'
   OR body REGEXP 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.'
   OR body CONTAINS 'BEGIN RSA PRIVATE KEY')
  AND resource.deployment.environment = 'production'
  ```

* **Aggregations:** Summarizing the data.
  SigNoz QB aggregations are expressions for logs and traces, supporting rich ways to slice data and answer questions like:

  **Risk of churn or attributing loss of business value**
  Say you’re running an e-commerce app. Your application occasionally errors, and you want to understand the total order value affected by those failures.
  ```sql
  sumIf(order.total, has_error = true)
  ```
  This has direct business impact. Aggregating a business attribute under a failure condition is what lets us answer “what % of requests failed?” to “what’s the total value of the orders that failed?”.

  **Throughput from raw data (i.e. rate)**
  Let’s say it’s sale day and traffic is spiking. Someone asks in the incident channel: 
  _What’s the request rate from shop ‘M&M toys’ on checkout right now?_
  ```yaml
  Signal: traces
  Filter: service.name = 'checkout' AND tenant.name = 'M&M toys'
  Aggregation: rate()
  ```

  **Understanding blast radius with count_distinct**
  Once the incident is over, you want to know how many users are impacted for the post-mortem.
  Using `count_distinct(user.id)` where `has_error = true` is how you get that number.

* **Group By:** Slicing the data.
  You annotate your data to dynamically slice and dice. They can be resource attributes, span/log attributes, intrinsic fields, JSON body paths. You can mix them freely in one breakdown.

  **Breakdown across contexts**
  Say you want the table every engineer is interested in i.e. latency of every endpoint of every service. The catch: `service.name` lives in resource attributes while `http.route` lives in span attributes.
  ```yaml
  Signal: traces
  Aggregation: p99(duration_nano)
  Group by: service.name, http.route
  ```
  Grouping works across both contexts transparently.

  **K8s events**
  Ship k8s events as logs using the otel receiver, and the cluster will tell you what’s wrong if you group it right. 
  _Which namespaces are seeing OOMKills, crash backoffs, and failed scheduling, and how often?_
  ```yaml
  Signal: logs
  Filter: k8s.event.reason IN ('OOMKilled', 'BackOff', 'FailedScheduling')
  Aggregation: count()
  Group by: k8s.namespace.name, k8s.event.reason
  ```

  **Rollout comparison in one chart**
  Say you rolled out a new version to 5% of users and want to know if it’s safe to continue. 
  _Is the new release slower or unstable?_
  ```yaml
  Signal: traces
  Aggregation: p99(duration_nano), countIf(has_error = true)
  Group by: service.version
  ```
  Both new and old releases show up as adjacent series of the same query. The regression is visible right away.

* **Having:** Filtering the results.
  The search expression decides which rows to consider for the aggregation. Having is used to filter the groups after aggregation.

  Say you count requests grouped by `http.route`. The chart comes back with 1000 series, including every health check, every random 404, every endpoint that served three requests this week. Number of these endpoints don’t really matter because they are not relevant in terms of number of requests.
  ```sql
  Having: count() > 1000
  ```
  This having filters away the low traffic and shows the endpoints with real traffic.

  **Other examples:**
  * Slow routes only: `p99(duration_nano) > 1000000000` (more than 1s)
  * Adoption: `count_distinct(user.id) > 100` (features that have more than 100 users adoption)