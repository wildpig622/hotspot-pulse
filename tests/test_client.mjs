import {test} from 'node:test';
import assert from 'node:assert/strict';
import {loadSnapshot,selectEvents,loadChanges} from '../site/hotspot-client.mjs';
const meta={api_version:'v2',schema_version:'2.0',expires_at:'2026-11-05T02:00:00Z',is_stale:false,using_cached_data:false};
const response=x=>async()=>({ok:true,json:async()=>x});
test('client rejects stale, cached and incompatible contracts',async()=>{
  await assert.rejects(loadSnapshot({fetchImpl:response({meta,data:[]}),now:'2026-11-06'}));
  await assert.rejects(loadSnapshot({fetchImpl:response({meta:{...meta,using_cached_data:true},data:[]}),now:'2026-11-04'}));
  await assert.rejects(loadSnapshot({fetchImpl:response({meta:{...meta,api_version:'v1'},data:[]}),now:'2026-11-04'}));
  assert.deepEqual((await loadSnapshot({fetchImpl:response({meta,data:[]}),now:'2026-11-04'})).data,[]);
});
test('client respects noncontinuous sessions and inactive status',()=>{
  const event={city_name:'重庆市',availability:'candidate',sessions:[{start_at:'2026-11-07',end_at:'2026-11-07'},{start_at:'2026-11-09',end_at:'2026-11-09'}]};
  assert.equal(selectEvents({data:[event]},{from:'2026-11-08',to:'2026-11-08'}).length,0);
  assert.equal(selectEvents({data:[event]},{cityName:'重庆市',from:'2026-11-09',to:'2026-11-09'}).length,1);
  assert.equal(selectEvents({data:[{...event,availability:'cancelled'}]}).length,0);
});
test('client requires full reset for expired or future cursor',async()=>{
  const fetchImpl=response({meta:{cursor:8,cursor_floor:5},data:[{cursor:6},{cursor:7},{cursor:8}]});
  assert.deepEqual((await loadChanges({since:7,fetchImpl})).data,[{cursor:8}]);
  await assert.rejects(loadChanges({since:4,fetchImpl}));
  await assert.rejects(loadChanges({since:9,fetchImpl}));
});
