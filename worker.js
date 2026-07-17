/* ============================================================================
   worker.js — houmonkango（訪問看護ナビ）に、soudan-naviからの読み込みを
   許可するためのCORSヘッダーを追加するCloudflare Worker
   ----------------------------------------------------------------------------
   このファイルは、houmonkango自体の見た目・機能には一切影響しません。
   静的ファイル（index.html・data_osaka.json 等）はこれまで通り配信しつつ、
   レスポンスに Access-Control-Allow-Origin ヘッダーを1つ追加するだけです。
   ============================================================================ */

// 👑 ここに、CORSを許可したいドメインを列挙する。
//    soudan-naviのURLが変わった場合や、他に読み込み元を増やしたい場合は、
//    この配列に追記するだけでよい。
const ALLOWED_ORIGINS = [
  'https://soudan-navi.coconanairo3731.workers.dev'
];

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin');

    // ブラウザが事前確認として送ってくる OPTIONS リクエスト（プリフライト）に対応。
    // 今回のような単純なGETリクエストでは通常発生しないが、将来的に
    // ヘッダーを追加する等の変更があっても壊れないよう、念のため対応しておく。
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: buildCorsHeaders(origin)
      });
    }

    // 通常のリクエストは、これまで通りASSETSに処理してもらう
    const response = await env.ASSETS.fetch(request);

    // レスポンスヘッダーに CORS 用のヘッダーを追加して返す
    const newHeaders = new Headers(response.headers);
    const corsHeaders = buildCorsHeaders(origin);
    Object.entries(corsHeaders).forEach(([key, value]) => newHeaders.set(key, value));

    return new Response(response.body, { status: response.status, headers: newHeaders });
  }
};

// 許可リストに含まれるOriginからのリクエストにだけ、CORSヘッダーを返す。
// リストに無いOriginや、Originヘッダー自体が無い場合（同一サイト内での通常の
// アクセス等）は、CORSヘッダーを付けない＝これまで通りの挙動のままにする。
function buildCorsHeaders(origin) {
  if (origin && ALLOWED_ORIGINS.includes(origin)) {
    return {
      'Access-Control-Allow-Origin': origin,
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Vary': 'Origin'
    };
  }
  return {};
}
