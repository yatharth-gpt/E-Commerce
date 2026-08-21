function getCart(){return JSON.parse(localStorage.getItem("om_cart")||"[]");}
function saveCart(c){localStorage.setItem("om_cart",JSON.stringify(c));updateCartCount();}
function updateCartCount(){const e=document.getElementById("cart-count");if(e)e.textContent=getCart().reduce((s,x)=>s+x.quantity,0);}
function addToCart(id,name,price,stock,quantity=1){const c=getCart(),q=Number(quantity);if(q<1)return;const x=c.find(p=>p.id===id),wanted=(x?x.quantity:0)+q;if(wanted>stock){alert("Only "+stock+" unit(s) available.");return;}if(x)x.quantity=wanted;else c.push({id,name,price:Number(price),stock:Number(stock),quantity:q});saveCart(c);alert(name+" added to cart.");}
function escapeHtml(v){return String(v).replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[m]));}
async function toggleFavorite(id,btn){const r=await fetch("/api/favorite/"+id,{method:"POST"});if(r.status===401){location.href="/login?next="+encodeURIComponent(location.pathname);return;}const d=await r.json();if(d.success)btn.textContent=d.active?"♥":"♡";}
document.addEventListener("DOMContentLoaded",updateCartCount);
