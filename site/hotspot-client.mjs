/* Consumer-side contract helper; no hotel data or credentials are required. */
export class FeedError extends Error {}
export async function loadSnapshot({baseUrl="https://wildpig622.github.io/hotspot-pulse/api/v2/",fetchImpl=globalThis.fetch,allowStale=false,allowCached=false,now=new Date()}={}) {
  const response=await fetchImpl(new URL("events.json",baseUrl),{cache:"no-store"});
  if(!response.ok) throw new FeedError("热点数据读取失败：HTTP "+response.status);
  const payload=await response.json();
  if(payload.meta?.api_version!=="v2"||payload.meta?.schema_version!=="2.0"||!Array.isArray(payload.data)) throw new FeedError("热点接口版本不兼容");
  const expires=Date.parse(payload.meta.expires_at);
  if(!allowStale&&(!Number.isFinite(expires)||new Date(now).getTime()>expires||payload.meta.is_stale)) throw new FeedError("热点数据已过期，请保留上次结果并显示更新时间");
  if(!allowCached&&payload.meta.using_cached_data) throw new FeedError("本轮更新失败，来源正提供保留快照");
  return payload;
}
export function selectEvents(snapshot,{cityName,from,to,includeInactive=false,reviewStatus}={}) {
  return snapshot.data.filter(row=>{
    if(cityName&&row.city_name!==cityName) return false;
    if(reviewStatus&&row.review_status!==reviewStatus) return false;
    if(!includeInactive&&(row.review_status==="rejected"||["cancelled","postponed","expired","needs_date_review","not_recently_observed"].includes(row.availability))) return false;
    return (row.sessions||[]).some(s=>(!from||s.end_at>=from)&&(!to||s.start_at<=to));
  });
}
export async function loadChanges({since=0,baseUrl="https://wildpig622.github.io/hotspot-pulse/api/v2/",fetchImpl=globalThis.fetch}={}) {
  const response=await fetchImpl(new URL("changes.json",baseUrl),{cache:"no-store"});
  if(!response.ok) throw new FeedError("变化记录读取失败");
  const payload=await response.json();
  if(since<payload.meta.cursor_floor||since>payload.meta.cursor) throw new FeedError("增量游标已失效，请重新读取完整快照");
  return {meta:payload.meta,data:payload.data.filter(row=>row.cursor>since)};
}
