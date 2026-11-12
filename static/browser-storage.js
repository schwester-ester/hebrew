/* Durable browser-only storage for the shared website, including recordings. */
(() => {
  let database;
  function open() {
    if(!database) database=new Promise((resolve,reject)=>{
      const request=indexedDB.open('ivrit-vocabulary',1);
      request.onupgradeneeded=()=>request.result.createObjectStore('state');
      request.onsuccess=()=>{request.result.onversionchange=()=>request.result.close();resolve(request.result);};
      request.onerror=()=>reject(new Error('Browser storage is unavailable. Allow site storage to keep your vocabulary.'));
      request.onblocked=()=>reject(new Error('Close other Ivrit tabs and reload to enable browser storage.'));
    });
    return database;
  }
  window.IvritStorage={
    async get(key,fallback) {
      const db=await open();
      return new Promise((resolve,reject)=>{
        const request=db.transaction('state').objectStore('state').get(key);
        request.onsuccess=()=>resolve(request.result ?? fallback);
        request.onerror=()=>reject(new Error('Could not read your saved vocabulary. Reload and try again.'));
      });
    },
    async set(key,value) {
      const db=await open();
      return new Promise((resolve,reject)=>{
        const transaction=db.transaction('state','readwrite');
        transaction.objectStore('state').put(value,key);
        transaction.oncomplete=()=>resolve();
        transaction.onabort=transaction.onerror=()=>reject(new Error('Could not save in this browser. Free some browser storage and export your cards before closing the page.'));
      });
    }
  };
})();
