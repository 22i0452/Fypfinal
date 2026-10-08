/* Canvas reflects actual PCM only. No decorative/random microphone activity. */
window.MedFlowMeter = (() => {
  const readings = new Map();
  function feed(id, samples) {
    const canvas = document.querySelector(`canvas[data-meter="${id}"]`);
    if (!canvas || !samples?.length) return;
    let squares=0,peak=0;for(const value of samples){squares+=value*value;peak=Math.max(peak,Math.abs(value));}
    const rms=Math.sqrt(squares/samples.length), db=rms?Math.max(-80,20*Math.log10(rms)):-80;
    readings.set(id,{rms,peak,db});
    const width=canvas.clientWidth || 500,height=canvas.clientHeight || 110,dpr=devicePixelRatio || 1;
    canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
    const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,width,height);
    ctx.strokeStyle='rgba(221,198,162,.12)';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(0,height/2);ctx.lineTo(width,height/2);ctx.stroke();
    ctx.strokeStyle=getComputedStyle(document.documentElement).getPropertyValue('--display-accent').trim() || '#ddc6a2';ctx.lineWidth=1.5;ctx.beginPath();
    for(let x=0;x<width;x++){const i=Math.min(samples.length-1,Math.floor(x*samples.length/width));const y=height/2-samples[i]*height*.45;(x?ctx.lineTo(x,y):ctx.moveTo(x,y));}ctx.stroke();
    document.querySelectorAll(`[data-meter-level="${id}"]`).forEach(el=>el.textContent=`${db.toFixed(0)} dBFS · ${peak>.98?'Near clipping':rms>.008?'Audio detected':'Quiet input'}`);
    const orbit=document.querySelector(`[data-meter-orbit="${id}"]`);if(orbit)orbit.style.setProperty('--input-level',Math.min(1,rms*8));
  }
  function reset(id){feed(id,new Float32Array(256));document.querySelectorAll(`[data-meter-level="${id}"]`).forEach(el=>el.textContent='Microphone inactive');}
  return {feed,reset,readings};
})();
