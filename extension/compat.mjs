// Some shipping Safari versions lack ReadableStream async iteration, used by
// PDF.js in both the display module and its worker. Preserve native support.
export function installStreamIterator(Stream=globalThis.ReadableStream){
  if(!Stream||typeof Stream.prototype[Symbol.asyncIterator]==='function')return;
  Object.defineProperty(Stream.prototype,Symbol.asyncIterator,{
    configurable:true,writable:true,
    value:async function*({preventCancel=false}={}){
      const reader=this.getReader();let completed=false,failed=false;
      try{
        while(true){
          let chunk;
          try{chunk=await reader.read();}catch(error){failed=true;throw error;}
          if(chunk.done){completed=true;return;}
          yield chunk.value;
        }
      }finally{
        try{if(!completed&&!failed&&!preventCancel)await reader.cancel();}
        finally{reader.releaseLock();}
      }
    }
  });
}
installStreamIterator();
