#!/system/bin/sh
# Friendly names for the projects present in the bundled stock DTBOs.
case "$(getprop ro.boot.prjname)" in
    18821) model='OnePlus 7 Pro' ;;
    18857) model='OnePlus 7' ;;
    18865|19863) model='OnePlus 7T' ;;
    19801) model='OnePlus 7T Pro' ;;
    19861) model='OnePlus 7T Pro 5G' ;;
    *) exit 0 ;;
esac

exec resetprop -n ro.product.model "$model"
