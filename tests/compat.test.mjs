import test from 'node:test';import assert from 'node:assert/strict';
import {installStreamIterator} from '../extension/compat.mjs';
function legacy(){class Stream extends ReadableStream{};Object.defineProperty(Stream.prototype,Symbol.asyncIterator,{value:undefined,configurable:true});installStreamIterator(Stream);return Stream;}
test('legacy streams yield every chunk and release their lock',async()=>{
 const Stream=legacy();let cancelled=false;
 const stream=new Stream({start(c){c.enqueue('first');c.enqueue('second');c.close();},cancel(){cancelled=true;}}),values=[];
 for await(const value of stream)values.push(value);
 assert.deepEqual(values,['first','second']);assert.equal(stream.locked,false);assert.equal(cancelled,false);
});
test('ending iteration cancels and releases a legacy stream',async()=>{
 const Stream=legacy();let cancelled=false;const stream=new Stream({start(c){c.enqueue(1);},cancel(){cancelled=true;}});
 for await(const value of stream){assert.equal(value,1);break;}
 assert.equal(cancelled,true);assert.equal(stream.locked,false);
});
test('legacy stream errors propagate without retaining the lock',async()=>{
 const Stream=legacy(),error=new Error('source failed'),stream=new Stream({start(c){c.error(error);}});
 await assert.rejects(async()=>{for await(const value of stream){void value;}},error);assert.equal(stream.locked,false);
});
test('native stream iteration is left in place',()=>{
 const original=ReadableStream.prototype[Symbol.asyncIterator];installStreamIterator(ReadableStream);assert.equal(ReadableStream.prototype[Symbol.asyncIterator],original);
});
