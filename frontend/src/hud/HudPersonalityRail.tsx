import { useEffect, useState } from "react"
import { api } from "../api"
import { applySessionTheme, type SessionMode } from "./sessionPersonality"

type Props={open:boolean;onToggle:()=>void;onSelected?:()=>void}
export function HudPersonalityRail({open,onToggle,onSelected}:Props){
 const [modes,setModes]=useState<SessionMode[]>([]); const [active,setActive]=useState("core"); const [auto,setAuto]=useState(true)
 async function refresh(){const p=await api<{active:SessionMode;modes:SessionMode[];manual_lock:boolean}>("/api/session-personality");setModes(p.modes||[]);setActive(p.active.id);setAuto(!p.manual_lock);applySessionTheme(p.active)}
 useEffect(()=>{void refresh()},[])
 async function select(id:string){const p=await api<{active:SessionMode}>("/api/session-personality",{method:"PUT",body:JSON.stringify({mode:id,manual:true})});setActive(p.active.id);setAuto(false);applySessionTheme(p.active);onSelected?.()}
 async function autoMode(){await api("/api/session-personality/auto",{method:"POST"});setAuto(true)}
 return <><button className={"hud-personality-tab"+(open?" active":"")} onClick={onToggle} aria-expanded={open} title="Personalities">◉</button>{open&&<aside className="hud-personality-drawer" aria-label="Personality selector"><div className="hud-personality-title">SPECIALISTS <button onClick={onToggle}>×</button></div><button className={"hud-personality-card"+(auto?" active":"")} onClick={()=>void autoMode()}><b>Auto / Anzu routing</b><small>Automatically hand work to the best specialist.</small></button>{modes.map(m=><button key={m.id} className={"hud-personality-card"+(active===m.id&&!auto?" active":"")} onClick={()=>void select(m.id)}><span className={"hud-personality-glyph "+(m.accent||"")}>{m.icon==="eye"?"◉":"●"}</span><span><b>{m.label}</b><small>{m.description||m.task_class_hint||"Specialist personality"}</small></span></button>)}</aside>}</>
}
