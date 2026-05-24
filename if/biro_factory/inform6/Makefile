LIB    = /Users/buntekuh/projects/Inform/inform/Library/lib611
INFORM = inform
FROTZ  = frotz

biro_factory.z5: biro_factory.inf
	$(INFORM) +$(LIB) ++. $< $@

play: biro_factory.z5
	$(FROTZ) $<

clean:
	rm -f biro_factory.z5

.PHONY: play clean
