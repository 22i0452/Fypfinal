// Optional offline PostgreSQL contract transport, never opens a listening socket.
import readline from 'node:readline';
import {pathToFileURL} from 'node:url';
const {PGlite} = await import(pathToFileURL(process.env.PGLITE_MODULE_PATH).href);
const db = new PGlite();
await db.waitReady;
for await (const line of readline.createInterface({input:process.stdin})) {
  try {
    const {sql, params=[]} = JSON.parse(line);
    let index=0;
    const result = await db.query(sql.replace(/%s/g,()=>`$${++index}`),params);
    process.stdout.write(JSON.stringify({rows:result.rows,count:result.affectedRows ?? result.rows.length})+'\n');
  } catch(error) {
    process.stdout.write(JSON.stringify({error:error.message,code:error.code})+'\n');
  }
}
await db.close();
