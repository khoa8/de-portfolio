WITH staging_rows AS (
    SELECT
        'lazada'::TEXT AS source,
        BTRIM(order_id)::TEXT AS order_code,
        order_date,
        NULLIF(BTRIM(order_status), '')::TEXT AS order_status,
        NULLIF(BTRIM(buyer_name), '')::TEXT AS buyer_name,
        total_amount::NUMERIC(18, 2) AS total_amount
    FROM stg_edw.e01_lazada_orders

    UNION ALL

    SELECT
        'shopee'::TEXT,
        BTRIM(order_id)::TEXT,
        order_date,
        NULLIF(BTRIM(order_status), '')::TEXT,
        NULLIF(BTRIM(buyer_name), '')::TEXT,
        total_amount::NUMERIC(18, 2)
    FROM stg_edw.e01_shopee_orders

    UNION ALL

    SELECT
        'tiki'::TEXT,
        BTRIM(order_id)::TEXT,
        order_date,
        NULLIF(BTRIM(order_status), '')::TEXT,
        NULLIF(BTRIM(buyer_name), '')::TEXT,
        total_amount::NUMERIC(18, 2)
    FROM stg_edw.e01_tiki_orders
),
hashed_rows AS (
    SELECT
        rows.*,
        MD5(
            JSONB_BUILD_OBJECT(
                'order_date', rows.order_date,
                'order_status', rows.order_status,
                'buyer_name', rows.buyer_name,
                'total_amount', rows.total_amount
            )::TEXT
        ) AS candidate_hash
    FROM staging_rows AS rows
),
variant_counts AS (
    SELECT
        source,
        order_code,
        order_date,
        order_status,
        buyer_name,
        total_amount,
        candidate_hash,
        COUNT(*)::BIGINT AS variant_row_count
    FROM hashed_rows
    GROUP BY
        source,
        order_code,
        order_date,
        order_status,
        buyer_name,
        total_amount,
        candidate_hash
),
variant_sets AS (
    SELECT
        source,
        order_code,
        SUM(variant_row_count)::BIGINT AS source_row_count,
        COUNT(*)::BIGINT AS distinct_variant_count,
        JSONB_AGG(
            JSONB_BUILD_OBJECT(
                'order_date', order_date,
                'order_status', order_status,
                'buyer_name', buyer_name,
                'total_amount', total_amount,
                'source_row_count', variant_row_count,
                'candidate_hash', candidate_hash
            )
            ORDER BY
                order_date DESC NULLS LAST,
                total_amount DESC NULLS LAST,
                order_status DESC NULLS LAST,
                buyer_name DESC NULLS LAST,
                candidate_hash DESC
        ) AS variants
    FROM variant_counts
    GROUP BY source, order_code
),
canonical AS (
    SELECT DISTINCT ON (source, order_code)
        source,
        order_code,
        order_date,
        order_status,
        buyer_name,
        total_amount,
        candidate_hash
    FROM variant_counts
    ORDER BY
        source,
        order_code,
        order_date DESC NULLS LAST,
        total_amount DESC NULLS LAST,
        order_status DESC NULLS LAST,
        buyer_name DESC NULLS LAST,
        candidate_hash DESC
),
raw_rows AS (
    SELECT
        canonical.source,
        canonical.order_code,
        JSONB_BUILD_OBJECT(
            'platform', canonical.source,
            'order_id', canonical.order_code,
            'order_date', canonical.order_date,
            'order_status', canonical.order_status,
            'buyer_name', canonical.buyer_name,
            'total_amount', canonical.total_amount,
            '_dedup', JSONB_BUILD_OBJECT(
                'source_row_count', variant_sets.source_row_count,
                'distinct_variant_count', variant_sets.distinct_variant_count,
                'canonical_candidate_hash', canonical.candidate_hash,
                'selection_rule',
                    'order_date_desc,total_amount_desc,order_status_desc,buyer_name_desc,candidate_hash_desc'
            ),
            '_variants', variant_sets.variants
        ) AS payload,
        canonical.order_date AT TIME ZONE 'UTC' AS src_event_ts
    FROM canonical
    JOIN variant_sets
      ON variant_sets.source = canonical.source
     AND variant_sets.order_code = canonical.order_code
)
INSERT INTO raw.orders_raw (
    source,
    order_code,
    payload,
    src_event_ts
)
SELECT
    source,
    order_code,
    payload,
    src_event_ts
FROM raw_rows
ON CONFLICT (source, order_code) DO UPDATE
SET payload = EXCLUDED.payload,
    src_event_ts = EXCLUDED.src_event_ts,
    ingested_at = CURRENT_TIMESTAMP
WHERE raw.orders_raw.payload IS DISTINCT FROM EXCLUDED.payload
   OR raw.orders_raw.src_event_ts IS DISTINCT FROM EXCLUDED.src_event_ts;
