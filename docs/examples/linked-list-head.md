# Linked List — insertion and removal at the head

Create a complete Java data-structures lesson from a teaching plan. The instructor explicitly selected Guided mode and approved drafts scene by scene.

**8 scenes · 114 manual animation steps · 1080p · Hebrew teaching content**

## Showcase

The finished PowerPoint preserves teacher-controlled advancement; the continuous video demonstrates the animation sequence. The original media is prepared separately for publication (see [example assets](assets-publication.md)).

## Guided walkthrough

The following selections are edited English translations of recorded Hebrew messages, not a recreated conversation. Event numbers identify captured messages. Scene names refer to final exported scenes, not historical drafts.

### 1. Choose Guided mode and agree on reusable examples

**Instructor — event 897**

> Yes, let’s go with Guided. Keep the same examples (I think two examples should lead the lesson). Break it into scenes and work on them one by one.

**Codex — event 910**

> We will use two examples throughout: insert 5 into 10 → 20 → 30, and remove 5 from 5 → 10 → 20 → 30.

**Scene:** HeadModel.

**What to learn:** A consistent visual vocabulary makes each later operation easier to compare.

### 2. Build and approve the first scene

**Instructor — event 926**

> Okay, let’s start.

**Codex — event 973**

> The first scene draft is ready: node structure, head reference, next links and a prediction question about head.getNext().

**Scene:** HeadModel.

**What to learn:** The first scene establishes the visual baseline.

### 3. Check classroom pacing

**Instructor — event 1086**

> Is there a pause between every line of code? So I can go through it with the students line by line?

**Codex — event 1088**

> Yes. In the main implementation there is a pause after every line, with the diagram showing the resulting state.

**Scene:** InsertSetter.

**What to learn:** A continuous video cannot demonstrate manual pacing by itself; the PowerPoint preserves the individual steps.

### 4. Request a precise pedagogical revision

**Instructor — event 1123**

> Use int instead of Integer. Declare it outside the if so it can also be used outside the if. Explain why.

**Codex — event 1171**

> A variable declared inside the if is only in scope within that block. Declaring it before the condition allows it to be used afterwards.

**Scene:** RemoveHead.

**What to learn:** The final scene incorporates the scope explanation, including initialization for the empty-list case.

### 5. Add student prediction exercises

**Instructor — event 1245**

> What exercise did you plan to make?

**Codex — event 1282**

> The practice scene includes completing insertion, correcting a removal call, and predicting removal from a singleton list.

**Scene:** PredictSummary.

**What to learn:** Answers are revealed individually, allowing the teacher to ask before showing the solution.

### 6. Export the finished lesson

**Instructor — event 1286**

> Prepare the complete presentation.

**Codex — event 1540**

> The full presentation is ready: eight scenes in 1080p, with 114 animation steps and manual pauses.

**Scene:** StaticRemove.

**What to learn:** The log also records an export-quality flag issue and a corrected render; final delivery was checked for resolution and embedded media.

## Explore every scene

| Scene | Focus |
| --- | --- |
| HeadModel | References and node structure |
| InsertConstructor | Insertion through a constructor |
| InsertSetter | Insertion using three statements |
| RemoveHead | Removal and variable scope |
| StaticInsert | External insertion operation |
| StaticRemove | External removal operation |
| EdgeCases | Boundary cases |
| PredictSummary | Prediction and practice |

## Reuse the project

The prepared source archive, scene catalog, storyboard and rendered Manim Slides archive accompany the media package. Use a compatible Manim Studio checkout and its [environment setup](../getting-started/installation.md). These historical exports are not independently tested standalone installers.

## Capture and validation notes

The research archive contains 15 captured user prompts and 55 model response events. The capture is incomplete; some opening turns and intermediate file versions may be missing. The walkthrough does not claim to reconstruct them.
