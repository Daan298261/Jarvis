import React, {useState} from 'react'
import {createRoot} from 'react-dom/client'
import {BrowserRouter} from 'react-router-dom'
import {PresenceHost} from './src/presence/PresenceHost'
import {DEFAULT_PRESENTATION_SETTINGS, type PresencePhase} from './src/presence/presenceTypes'
import './src/presence/presence.css'
function Check(){
 const [phase,setPhase]=useState<PresencePhase>('idle')
 const [settings,setSettings]=useState({...DEFAULT_PRESENTATION_SETTINGS,requestedPresence:'humanoid' as const, performancePreset:'cinematic' as const,reducedMotion:'full' as const})
 return <><div style={{padding:16,display:'flex',gap:20}}><label>Phase <select value={phase} onChange={e=>setPhase(e.target.value as PresencePhase)}>{['idle','listening','thinking','executing','speaking','waiting','alert','offline'].map(p=><option key={p}>{p}</option>)}</select></label><label>Reduce motion <input type="checkbox" onChange={e=>setSettings(s=>({...s,reducedMotion:e.target.checked?'reduce':'full'} as typeof s))}/></label><label>Efficient <input type="checkbox" onChange={e=>setSettings(s=>({...s,performancePreset:e.target.checked?'efficient':'cinematic'} as typeof s))}/></label><button onClick={()=>document.querySelector('canvas')?.dispatchEvent(new Event('webglcontextlost',{cancelable:true}))}>Test context loss</button></div><PresenceHost settings={settings} snapshot={{phase,intensity:0.7,connected:phase!=='offline',runningTaskCount:0,decisionCount:0,systemDegraded:phase==='alert',audioLevel:phase==='speaking'?0.6:0}}/></>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><BrowserRouter><Check/></BrowserRouter></React.StrictMode>)
