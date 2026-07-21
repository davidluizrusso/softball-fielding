You are helping me build a service that optimizes softball defensive assignments for my co-ed league. The assignment should be accomplished via an optimization routine, and ideally this will be hosted on a website that I can access. It is necessary that the optimization occur quickly because there will be times when people will cancel last minute and won't be able to play. The inputs to this optimization should be as follows:

1. Roster (with genders)
2. Positional preferences
3. Availability by game

In slowpitch softball, there are 10 positions: pitcher, catcher, first base, second base, third base, shortstop, left field, left center field, right center field, and right field (P, C, 1B, 2B, 3B, SS, LF, LC, RC, RF). 

The reason we need to optimize scheduling is because in slowpitch softball only 10 people can field at a time, and we will have more than 10 people on our roster. Additionally, in order to field 10 people we must have at LEAST 4 women on the field (with at least one woman in the outfield and at least one woman in the infield). If we can only field 3 women, then we can only have 9 total fielders (even if there are surplus men available to play). 

The minimum number of people needed to field a team is 8. When we have 8 players, we play with no catcher and we play with no RF. In the event that we only play with 8 people, then anyone whose preference contains RF will automatically have RC as a preference (but only when we have 8 people). 

The goal is this program is to assign players to fielding positions given their preferences and availabilities. THe main goal is to field legal fielding lineups, the second goal is to get equal playing time (as much as possible and positional preferences will allow), and the third goal is to maintain consistency in fielding positions so that people aren't playing more than two distinct positions wihtin a single game. 

The website should allow for multiple people to run it at the same time, but in general the volume will be very low. The output should be a matrix with innings as rows (there are 7 innings in a softball game), positions as columns, and people's names as values.

I want this to cost as little as possible, but I also don't want to manage a bunch of infra. I want the quickest possible path to a website that others can access. I do not need a unique domain name. 
