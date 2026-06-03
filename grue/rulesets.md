Must have	look, examine, take, drop, go, inventory, open, close, put in, put on, remove
Almost always	lock, unlock, wear, remove (worn), give, show, enter, exit, read
Common	eat, drink, push, pull, turn, attack, wait, again
Leave to author	kiss, pray, sing, buy, swim, climb, smell, taste, listen

. Movement and rooms
Kinds: none (exits are plain properties)
Handlers: go direction, enter object, exit, look
Missing primitive: move obj to dest

2. Examination
Handlers: examine object, read object, search object, look in Container, look under object

3. Inventory
Handlers: take object, drop object, inventory
Kind needed: none — player already acts as a container

4. Containers
Class: Container
Kind: opened: closed, open — lockable: false, true — key: unset
Handlers: open Container, close Container, lock Container with object, unlock Container with object, put object in Container, take object from Container

5. Supporters
Class: Supporter
Handlers: put object on Supporter, take object from Supporter

6. Doors
Already in language — just needs open/close/lock/unlock handlers

7. Wearables
Kind: worn: carried, worn
Handlers: wear object, remove object (worn)

8. Edibles
Kind: edible: false, true
Handlers: eat object, drink object

9. Lighting
Kind: lit: dark, lit on rooms — luminous: false, true on objects
Handlers: switch on object, switch off object, light object, extinguish object
Behaviour: player can't see in dark rooms, light sources illuminate

10. NPCs
Class: Actor
Kind: alive: dead, alive
Handlers: talk to Actor, ask Actor about object, tell Actor about object, give object to Actor, show object to Actor
Orders: on order take, on order drop (robot, take the flask)

11. Combat (optional)
Handlers: attack object, attack object with object
Kind: health: 0 as numeric property

12. Standard responses
The "you can't do that" messages — override points the author can replace

13. Meta
Handlers: wait, again — implemented in standard library calling interface
(undo, save, restore already noted as library + interface)