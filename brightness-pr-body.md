Selecting a persona forces version B, which bypassed the detailed artwork for procedural masks. RFC-0210 restores all fourteen original persona artworks in B as smoothed particle reliefs with front/rear depth and live gaze. Both humanoid assets remain available.

All fourteen personas and both humanoids now have distinct, restrained idle motion profiles: bird hover/feather movement, owl head tilt, water drift, serpent sway, measured nodding and breathing. Shared uniforms add bounded edge movement/ripples to the persona reliefs. Reduced motion and zero animation disable the motions. Depth smoothing removes corrugated surface ridges; peripheral adornments are gently dimmed and B bloom is reduced for clearer, calmer faces. These are depth reconstructions of artwork, not rigged anatomical meshes.

Portrait exposure now compensates for dark authored colours, rear-surface dimming and sprite area against the measured production humanoid light target. A single exposure multiplier retains colour ratios and shading; already bright portraits and both humanoids retain their lighting. The arbitrary B-only glow boost is removed. Browser checks verified all fourteen calibrated B exposures, including Anzu and dark purple Bragi, at maximum brightness. Density and point sizes are unchanged.

Brightness and Density share persistent controls in Persona and the HUD Appearance menu, which keeps the avatar visible during adjustment. Density uses stable scattered sampling, preserving the whole silhouette and dot size instead of leaving raster bars. Revision guards prevent delayed settings responses from undoing newer A/B selections.

Validation: frontend build/lint pass with existing warnings; 67 frontend tests pass, including scattered thinning, animation bounds/reduced motion, portrait depth and settings response races; 20 focused Python tests pass. Browser verification covered all fourteen B avatars, both humanoid animations, A/B switching, pointer gaze, density and reduced motion. Full local pytest did not complete; full CI remains outstanding.

The built frontend was copied to the owner's installed frontend with a complete backup before each update. Installed-page acceptance remains unverified because the existing local backend timed out on HTTP requests. No installer or backend source changes.

